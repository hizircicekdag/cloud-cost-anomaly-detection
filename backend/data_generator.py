import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def generate_synthetic_cur(start_date_str="2025-11-27", num_days=180, output_path="aws_cur_synthetic.csv"):

    np.random.seed(42)  # For reproducible synthetic data
    
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    date_list = [start_date + timedelta(days=i) for i in range(num_days)]
    
    records = []
    
    # Base costs and behaviors for services
    # EC2: High cost, weekly seasonality (lower on weekends)
    # RDS: Stable medium cost, low seasonality
    # S3: Low base cost but linear cumulative growth (data accumulates)
    # DynamoDB: Stable low cost
    # DataTransfer: Low base cost, highly volatile
    
    anomaly_labels = [] # List of dicts representing ground truth anomalies
    
    # Pre-define injected anomalies (Day index, Service, Cost increase, Duration, Description)
    injected_anomalies = [
        # Anomaly 1: EC2 Leak - Staging GPU instance left running over weekend
        {"day_idx": 30, "service": "AmazonEC2", "spike": 350.0, "duration": 3, "reason": "EC2 Sızıntısı (p3.2xlarge sunucu açık unutulmuş)"},
        # Anomaly 2: Data Transfer Spike - Big DB Export / Exfiltration Simulation
        {"day_idx": 75, "service": "AWSDataTransfer", "spike": 450.0, "duration": 1, "reason": "Aşırı Veri Transferi (kontrolsüz yedek kopyalama)"},
        # Anomaly 3: RDS Storage Expansion - Database log table filled disk
        {"day_idx": 110, "service": "AmazonRDS", "spike": 180.0, "duration": 5, "reason": "RDS Depolama Büyümesi (veritabanı log dosyası doldu)"},
        # Anomaly 4: DynamoDB Provisioned capacity misconfiguration during load test
        {"day_idx": 150, "service": "AmazonDynamoDB", "spike": 220.0, "duration": 2, "reason": "DynamoDB Yazma Kapasite Sıçraması (yük testi ayarları açık kaldı)"}
    ]

    
    for i, dt in enumerate(date_list):
        date_str = dt.strftime("%Y-%m-%d")
        day_of_week = dt.weekday()  # 0=Monday, 6=Sunday
        is_weekend = day_of_week >= 5
        
        # 1. AmazonEC2
        ec2_base = 120.0 + (i * 0.15)  # Slow upward trend
        ec2_seasonal = -35.0 if is_weekend else 10.0  # Lower cost on weekends
        ec2_noise = np.random.normal(0, 5.0)
        ec2_cost = max(10.0, ec2_base + ec2_seasonal + ec2_noise)
        ec2_usage = ec2_cost / 0.096  # proxy usage amount (e.g. instance-hours)
        
        # 2. AmazonRDS
        rds_base = 60.0 + (i * 0.05)
        rds_seasonal = -5.0 if is_weekend else 2.0
        rds_noise = np.random.normal(0, 2.0)
        rds_cost = max(20.0, rds_base + rds_seasonal + rds_noise)
        rds_usage = rds_cost / 0.15  # proxy hours
        
        # 3. AmazonS3
        s3_base = 15.0 + (i * 0.4)  # Cumulative storage growth
        s3_noise = np.random.normal(0, 1.0)
        s3_cost = max(5.0, s3_base + s3_noise)
        s3_usage = s3_cost / 0.023  # proxy GBs
        
        # 4. AmazonDynamoDB
        ddb_base = 25.0
        ddb_noise = np.random.normal(0, 0.8)
        ddb_cost = max(5.0, ddb_base + ddb_noise)
        ddb_usage = ddb_cost / 0.00065  # proxy Write Units
        
        # 5. AWSDataTransfer
        dt_base = 8.0 + (i * 0.02)
        dt_noise = np.random.exponential(scale=3.0)  # skewed distribution
        dt_cost = max(1.0, dt_base + dt_noise)
        dt_usage = dt_cost / 0.09  # proxy GBs out
        
        costs = {
            "AmazonEC2": (ec2_cost, ec2_usage, "RunInstances"),
            "AmazonRDS": (rds_cost, rds_usage, "CreateDBInstance"),
            "AmazonS3": (s3_cost, s3_usage, "TimedStorage-ByteHrs"),
            "AmazonDynamoDB": (ddb_cost, ddb_usage, "ProvisionedWriteCapacityUnit"),
            "AWSDataTransfer": (dt_cost, dt_usage, "DataTransfer-Out-Bytes")
        }
        
        # Apply pre-defined anomalies
        current_anomalies = []
        for anomaly in injected_anomalies:
            start_idx = anomaly["day_idx"]
            end_idx = start_idx + anomaly["duration"]
            if start_idx <= i < end_idx:
                srv = anomaly["service"]
                cost, usage, op = costs[srv]
                costs[srv] = (cost + anomaly["spike"], usage * (1 + anomaly["spike"]/cost), op)
                current_anomalies.append(anomaly["reason"])
                
        # Generate CUR records for this day
        line_item_idx = 1
        for srv, (cost, usage, op) in costs.items():
            # Add some minor sub-items to simulate detailed CUR
            records.append({
                "identity/LineItemId": f"li-{date_str}-{srv}-{line_item_idx}",
                "bill/BillingPeriodStartDate": dt.replace(day=1).strftime("%Y-%m-%d 00:00:00"),
                "lineItem/UsageStartDate": f"{date_str} 00:00:00",
                "lineItem/ProductCode": srv,
                "lineItem/UsageType": f"{srv}-usage-type",
                "lineItem/Operation": op,
                "lineItem/UnblendedCost": float(cost),
                "lineItem/UsageAmount": float(usage),
                "anomaly/IsAnomaly": 1 if len(current_anomalies) > 0 and srv == [a["service"] for a in injected_anomalies if a["reason"] in current_anomalies][0] else 0,
                "anomaly/AnomalyReason": current_anomalies[0] if len(current_anomalies) > 0 and srv == [a["service"] for a in injected_anomalies if a["reason"] in current_anomalies][0] else "Normal"
            })
            line_item_idx += 1
            
    df = pd.DataFrame(records)
    df.to_csv(output_path, index=False)
    print(f"Generated {len(df)} billing records in '{output_path}'.")
    return df

def load_daily_costs(csv_path="aws_cur_synthetic.csv"):
    """
    Loads CUR data and aggregates by day.
    Returns:
        pd.DataFrame: A DataFrame indexed by Date with columns:
                      - TotalCost
                      - Service-wise costs
                      - IsAnomaly (ground truth, 1 if any service was anomalous that day)
                      - AnomalyReason (ground truth reason)
    """
    if not os.path.exists(csv_path):
        generate_synthetic_cur(output_path=csv_path)
        
    df = pd.read_csv(csv_path)
    
    # Extract date
    df['Date'] = pd.to_datetime(df['lineItem/UsageStartDate']).dt.date
    
    # Daily aggregation of costs
    daily_total = df.groupby('Date')['lineItem/UnblendedCost'].sum().reset_index(name='TotalCost')
    
    # Service wise daily costs
    daily_services = df.pivot_table(
        index='Date', 
        columns='lineItem/ProductCode', 
        values='lineItem/UnblendedCost', 
        aggfunc='sum'
    ).reset_index()
    
    # Ground truth anomalies
    daily_anomalies = df.groupby('Date').agg({
        'anomaly/IsAnomaly': 'max',
        'anomaly/AnomalyReason': lambda x: next((v for v in x if v != "Normal"), "Normal")
    }).reset_index()
    
    # Merge everything
    daily_df = daily_total.merge(daily_services, on='Date')
    daily_df = daily_df.merge(daily_anomalies, on='Date')
    
    daily_df.set_index('Date', inplace=True)
    daily_df.index = pd.to_datetime(daily_df.index)
    return daily_df

def inject_dynamic_anomaly(csv_path, date_str, service, spike_amount, reason):

    if not os.path.exists(csv_path):
        generate_synthetic_cur(output_path=csv_path)
        
    df = pd.read_csv(csv_path)
    
    # Format target date
    target_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d 00:00:00")
    
    # Check if the row for this date and service exists
    mask = (df['lineItem/UsageStartDate'] == target_date) & (df['lineItem/ProductCode'] == service)
    
    if mask.any():
        df.loc[mask, 'lineItem/UnblendedCost'] += spike_amount
        df.loc[mask, 'lineItem/UsageAmount'] *= (1 + spike_amount / max(1.0, df.loc[mask, 'lineItem/UnblendedCost'].values[0] - spike_amount))
        df.loc[mask, 'anomaly/IsAnomaly'] = 1
        df.loc[mask, 'anomaly/AnomalyReason'] = f"Manual Injection: {reason}"
        
        # Save back to CSV
        df.to_csv(csv_path, index=False)
        print(f"Successfully injected anomaly: {reason} of ${spike_amount} to {service} on {date_str}")
        return True
    else:
        print(f"Warning: Could not find record for date {date_str} and service {service}")
        return False

if __name__ == "__main__":
    generate_synthetic_cur()
    df_daily = load_daily_costs()
    print("Daily Cost Head:")
    print(df_daily.head())
    print("\nInjected Anomalies in ground truth:")
    print(df_daily[df_daily['anomaly/IsAnomaly'] == 1][['TotalCost', 'anomaly/AnomalyReason']])
