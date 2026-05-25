import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL
from sklearn.ensemble import IsolationForest

def detect_stl(df_daily, threshold_multiplier=3.0):
    """
    Applies STL (Seasonal and Trend decomposition using Loess) to Daily Cost.
    Detects anomalies on the Residual component using Median Absolute Deviation (MAD).
    Returns:
        pd.DataFrame: Contains columns 'trend', 'seasonal', 'resid', 'anomaly_stl', 'score_stl'
    """
    series = df_daily['TotalCost']
    
    # STL requires a continuous date index with frequency
    # We ensure daily frequency ('D')
    series = series.asfreq('D')
    
    # If there are missing values (shouldn't be, but for safety), interpolate them
    if series.isnull().any():
        series = series.interpolate(method='linear')
        
    # Decompose: weekly seasonality (period=7)
    res = STL(series, period=7, robust=True).fit()
    
    trend = res.trend
    seasonal = res.seasonal
    resid = res.resid
    
    # Compute Median Absolute Deviation (MAD) of residuals
    median_resid = np.median(resid)
    mad = np.median(np.abs(resid - median_resid))
    
    # Prevent division by zero
    if mad == 0:
        mad = 1e-5
        
    # Calculate anomaly score (Z-like score based on MAD)
    scores = np.abs(resid - median_resid) / mad
    
    # Flag points exceeding the threshold
    anomalies = (scores > threshold_multiplier).astype(int)
    
    result = pd.DataFrame({
        'trend': trend,
        'seasonal': seasonal,
        'resid': resid,
        'score_stl': scores,
        'anomaly_stl': anomalies
    }, index=series.index)
    
    return result

def detect_isolation_forest(df_daily, contamination=0.05):
    """
    Applies Isolation Forest to detect cost anomalies.
    Features used:
        - TotalCost
        - Cost Difference (1-day delta)
        - Day of Week (0-6)
        - Rolling 7-day average Cost
    Returns:
        pd.DataFrame: Contains columns 'anomaly_iforest', 'score_iforest'
    """
    df = df_daily.copy()
    
    # Engineer features
    df['cost_diff'] = df['TotalCost'].diff().fillna(0)
    df['day_of_week'] = df.index.dayofweek
    df['rolling_mean_7'] = df['TotalCost'].rolling(window=7, min_periods=1).mean()
    
    # Define feature set
    features = ['TotalCost', 'cost_diff', 'day_of_week', 'rolling_mean_7']
    X = df[features].values
    
    # Initialize and fit Isolation Forest
    model = IsolationForest(contamination=contamination, random_state=42)
    model.fit(X)
    
    # Predict (-1 for anomalies, 1 for normal)
    preds = model.predict(X)
    anomalies = (preds == -1).astype(int)
    
    # Higher anomaly score means more anomalous (Isolation Forest decision function returns opposite, so we invert it)
    scores = -model.decision_function(X)
    # Normalize score to be positive
    scores = (scores - scores.min()) / (scores.max() - scores.min() + 1e-5)
    
    result = pd.DataFrame({
        'anomaly_iforest': anomalies,
        'score_iforest': scores
    }, index=df.index)
    
    return result

def detect_zscore(df_daily, window=14, threshold=2.5):
    """
    Applies a rolling Z-score method on the daily total cost.
    Z = (Cost - Rolling Mean) / Rolling StdDev
    Only positive spikes are considered cost anomalies.
    Returns:
        pd.DataFrame: Contains columns 'anomaly_zscore', 'score_zscore'
    """
    series = df_daily['TotalCost']
    
    rolling_mean = series.rolling(window=window, min_periods=7).mean()
    rolling_std = series.rolling(window=window, min_periods=7).std()
    
    # Fill starting values where standard deviation is NaN or zero
    rolling_std = rolling_std.fillna(series.std()).replace(0, 1e-5)
    rolling_mean = rolling_mean.fillna(series.mean())
    
    # Compute Z-score
    z_scores = (series - rolling_mean) / rolling_std
    
    # Anomaly if Z-score is greater than threshold (positive spikes only)
    anomalies = (z_scores > threshold).astype(int)
    
    # Keep negative scores at 0 for score display
    display_scores = z_scores.clip(lower=0)
    
    result = pd.DataFrame({
        'anomaly_zscore': anomalies,
        'score_zscore': display_scores
    }, index=series.index)
    
    return result

def perform_root_cause_attribution(df_daily, anomaly_date, models_detected):
    """
    Attributes an anomaly on a specific date to the responsible service.
    Compares the cost spike of each service relative to its historical mean.
    """
    # Lookback window to compute normal baselines (e.g. past 14 days)
    end_date = pd.to_datetime(anomaly_date)
    start_date = end_date - pd.Timedelta(days=14)
    
    historical = df_daily.loc[df_daily.index < end_date]
    if len(historical) < 5:
        # If not enough history, use all available data before the date
        historical = df_daily
        
    services = ['AmazonEC2', 'AmazonRDS', 'AmazonS3', 'AmazonDynamoDB', 'AWSDataTransfer']
    
    attribution_details = []
    total_spike = 0
    
    # Get costs on the anomaly day
    day_costs = df_daily.loc[end_date]
    
    for service in services:
        if service not in df_daily.columns:
            continue
            
        service_historical_mean = historical[service].mean()
        service_historical_std = historical[service].std()
        if pd.isna(service_historical_std) or service_historical_std == 0:
            service_historical_std = 1.0
            
        current_cost = day_costs[service]
        
        # Calculate spike amount and significance (z-score for service)
        spike = current_cost - service_historical_mean
        service_z = spike / service_historical_std
        
        if spike > 0:
            total_spike += spike
            attribution_details.append({
                "service": service,
                "current_cost": float(current_cost),
                "normal_cost": float(service_historical_mean),
                "spike_amount": float(spike),
                "service_z": float(service_z)
            })
            
    # Sort by spike amount descending
    attribution_details.sort(key=lambda x: x["spike_amount"], reverse=True)
    
    # Calculate percentage contribution
    for item in attribution_details:
        item["contribution_pct"] = (item["spike_amount"] / total_spike * 100) if total_spike > 0 else 0
        
    primary_suspect = "Unknown"
    confidence = "Low"
    root_cause = "No clear spike detected in individual services."
    
    if attribution_details:
        top = attribution_details[0]
        primary_suspect = top["service"]
        
        # Determine confidence
        if top["contribution_pct"] > 60 and top["service_z"] > 3.0:
            confidence = "Yüksek"
        elif top["service_z"] > 2.0:
            confidence = "Orta"
        else:
            confidence = "Düşük"
            
        # Write user-friendly reason in Turkish
        if primary_suspect == "AmazonEC2":
            root_cause = f"EC2 (Sanal Sunucu) kullanımında olağan dışı harcama artışı (Normalin ${top['spike_amount']:.2f} üzerinde). Kapatılmamış staging/test sunucuları veya hatalı otomatik ölçeklendirme (Auto-scaling) tetiklenmiş olabilir."
        elif primary_suspect == "AmazonRDS":
            root_cause = f"İlişkisel Veritabanı (RDS) maliyetlerinde anomali (Normalin ${top['spike_amount']:.2f} üzerinde). Veritabanı boyutunun kontrolsüz büyümesi, gereksiz yedekleme dosyaları veya yüksek kapasiteli veritabanı sınıfına geçiş yapılmış olabilir."
        elif primary_suspect == "AmazonS3":
            root_cause = f"S3 Depolama maliyetlerinde artış (Normalin ${top['spike_amount']:.2f} üzerinde). Büyük boyutlu dosya yüklemeleri, sürekli çalışan yedekleme döngüleri veya aşırı API okuma/yazma (PUT/GET) istekleri tespit edildi."
        elif primary_suspect == "AmazonDynamoDB":
            root_cause = f"DynamoDB (NoSQL Veritabanı) maliyet anomalisi (Normalin ${top['spike_amount']:.2f} üzerinde). Yük testleri sırasında provizyon edilen okuma/yazma kapasite limitlerinin (RCU/WCU) yüksek unutulmuş olması muhtemel."
        elif primary_suspect == "AWSDataTransfer":
            root_cause = f"Ağ veri transfer (Data Transfer) ücretlerinde ani sıçrama (Normalin ${top['spike_amount']:.2f} üzerinde). Büyük veri tabanı dışa aktarımları, bölgeler arası kontrolsüz veri kopyalama veya sık tekrarlanan ağ trafiği tetiklenmiş."
            
    return {
        "date": end_date.strftime("%Y-%m-%d"),
        "total_cost": float(day_costs["TotalCost"]),
        "detected_by": models_detected, # e.g. ["STL", "Z-Score"]
        "primary_service": primary_suspect,
        "confidence": confidence,
        "root_cause_explanation": root_cause,
        "breakdown": attribution_details
    }

