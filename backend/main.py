import os
import csv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pandas as pd
import numpy as np
from datetime import datetime

# Import local modules
from data_generator import load_daily_costs, inject_dynamic_anomaly, generate_synthetic_cur
from detector import detect_stl, detect_isolation_forest, detect_zscore, perform_root_cause_attribution
from evaluation import evaluate_models

app = FastAPI(title="Cloud Cost Anomaly Detection API")

# Enable CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CSV_PATH = "aws_cur_synthetic.csv"

# Ensure initial data exists
if not os.path.exists(CSV_PATH):
    print("No database CSV found. Generating initial synthetic CUR data...")
    generate_synthetic_cur(output_path=CSV_PATH)

class AnomalyInjectionRequest(BaseModel):
    date: str
    service: str
    spike_amount: float
    reason: str

def save_alerts_to_csv(alerts):
    csv_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "../detected_anomalies.csv"))
    try:
        with open(csv_file, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # Header
            writer.writerow(["Tarih", "Toplam Maliyet ($)", "Tespit Eden Modeller", "Birincil Şüpheli Servis", "Güven Derecesi", "Kök Neden Açıklaması", "Maliyet Sıçramaları Detayları"])
            for a in alerts:
                detected_by_str = ", ".join(a["detected_by"]) if a["detected_by"] else "Referans Veri"
                breakdown_strs = []
                for item in a["breakdown"]:
                    breakdown_strs.append(f"{item['service']}: +%{item['contribution_pct']:.1f} (+${item['spike_amount']:.2f})")
                breakdown_summary = " | ".join(breakdown_strs)
                writer.writerow([a["date"], f"${a['total_cost']:.2f}", detected_by_str, a["primary_service"], a["confidence"], a["root_cause_explanation"], breakdown_summary])
        print(f"Saved {len(alerts)} alerts to CSV at {csv_file}")
    except Exception as e:
        print(f"Error saving alerts to CSV: {e}")

@app.get("/api/summary")
def get_summary():
    try:
        df = load_daily_costs(CSV_PATH)
        total_cost = df['TotalCost'].sum()
        avg_daily = df['TotalCost'].mean()
        num_days = len(df)
        
        # Calculate anomalies detected by each method
        stl_res = detect_stl(df)
        iforest_res = detect_isolation_forest(df)
        zscore_res = detect_zscore(df)
        
        return {
            "total_cost": float(total_cost),
            "avg_daily_cost": float(avg_daily),
            "num_days": int(num_days),
            "anomalies_stl": int(stl_res['anomaly_stl'].sum()),
            "anomalies_iforest": int(iforest_res['anomaly_iforest'].sum()),
            "anomalies_zscore": int(zscore_res['anomaly_zscore'].sum()),
            "ground_truth_anomalies": int(df['anomaly/IsAnomaly'].sum())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cost-data")
def get_cost_data(
    stl_threshold: float = 3.0,
    iforest_contamination: float = 0.05,
    zscore_threshold: float = 2.5
):
    try:
        df = load_daily_costs(CSV_PATH)
        
        # Run detection models
        stl_res = detect_stl(df, threshold_multiplier=stl_threshold)
        iforest_res = detect_isolation_forest(df, contamination=iforest_contamination)
        zscore_res = detect_zscore(df, threshold=zscore_threshold)
        
        # Combine results
        combined = pd.DataFrame(index=df.index)
        combined['TotalCost'] = df['TotalCost']
        
        # Service costs
        services = ['AmazonEC2', 'AmazonRDS', 'AmazonS3', 'AmazonDynamoDB', 'AWSDataTransfer']
        for srv in services:
            if srv in df.columns:
                combined[srv] = df[srv]
            else:
                combined[srv] = 0.0
                
        # Ground Truth
        combined['is_anomaly_gt'] = df['anomaly/IsAnomaly']
        combined['anomaly_reason_gt'] = df['anomaly/AnomalyReason']
        
        # Model outputs
        combined['trend'] = stl_res['trend']
        combined['seasonal'] = stl_res['seasonal']
        combined['resid'] = stl_res['resid']
        combined['anomaly_stl'] = stl_res['anomaly_stl']
        combined['score_stl'] = stl_res['score_stl']
        
        combined['anomaly_iforest'] = iforest_res['anomaly_iforest']
        combined['score_iforest'] = iforest_res['score_iforest']
        
        combined['anomaly_zscore'] = zscore_res['anomaly_zscore']
        combined['score_zscore'] = zscore_res['score_zscore']
        
        # Format response
        records = []
        for date, row in combined.iterrows():
            records.append({
                "date": date.strftime("%Y-%m-%d"),
                "TotalCost": float(row["TotalCost"]),
                "services": {srv: float(row[srv]) for srv in services},
                "is_anomaly_gt": int(row["is_anomaly_gt"]),
                "anomaly_reason_gt": str(row["anomaly_reason_gt"]),
                "stl": {
                    "trend": float(row["trend"]),
                    "seasonal": float(row["seasonal"]),
                    "resid": float(row["resid"]),
                    "is_anomaly": int(row["anomaly_stl"]),
                    "score": float(row["score_stl"])
                },
                "iforest": {
                    "is_anomaly": int(row["anomaly_iforest"]),
                    "score": float(row["score_iforest"])
                },
                "zscore": {
                    "is_anomaly": int(row["anomaly_zscore"]),
                    "score": float(row["score_zscore"])
                }
            })
            
        return records
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/alerts")
def get_alerts(
    model: str = Query("any", enum=["any", "stl", "iforest", "zscore", "gt"]),
    stl_threshold: float = 3.0,
    iforest_contamination: float = 0.05,
    zscore_threshold: float = 2.5
):
    try:
        df = load_daily_costs(CSV_PATH)
        
        stl_res = detect_stl(df, threshold_multiplier=stl_threshold)
        iforest_res = detect_isolation_forest(df, contamination=iforest_contamination)
        zscore_res = detect_zscore(df, threshold=zscore_threshold)
        
        alerts = []
        
        # Evaluate day by day
        for dt in df.index:
            detected_by = []
            if stl_res.loc[dt, 'anomaly_stl'] == 1:
                detected_by.append("STL")
            if iforest_res.loc[dt, 'anomaly_iforest'] == 1:
                detected_by.append("Isolation Forest")
            if zscore_res.loc[dt, 'anomaly_zscore'] == 1:
                detected_by.append("Z-Score")
                
            gt_is_anomaly = int(df.loc[dt, 'anomaly/IsAnomaly'])
            gt_reason = str(df.loc[dt, 'anomaly/AnomalyReason'])
            
            # Filter matches based on selected model filter
            should_include = False
            if model == "any" and (len(detected_by) > 0 or gt_is_anomaly):
                should_include = True
            elif model == "stl" and "STL" in detected_by:
                should_include = True
            elif model == "iforest" and "Isolation Forest" in detected_by:
                should_include = True
            elif model == "zscore" and "Z-Score" in detected_by:
                should_include = True
            elif model == "gt" and gt_is_anomaly:
                should_include = True
                
            if should_include:
                # Perform root cause attribution
                attr = perform_root_cause_attribution(df, dt, detected_by)
                attr["is_anomaly_gt"] = gt_is_anomaly
                attr["anomaly_reason_gt"] = gt_reason
                alerts.append(attr)
                
        # Sort alerts chronologically (newest first)
        alerts.sort(key=lambda x: x["date"], reverse=True)
        
        # Persist alerts to CSV as requested in proposal Section 4.4
        if model == "any":
            save_alerts_to_csv(alerts)
            
        return alerts
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/metrics")
def get_metrics(
    stl_threshold: float = 3.0,
    iforest_contamination: float = 0.05,
    zscore_threshold: float = 2.5
):
    try:
        df = load_daily_costs(CSV_PATH)
        
        stl_res = detect_stl(df, threshold_multiplier=stl_threshold)
        iforest_res = detect_isolation_forest(df, contamination=iforest_contamination)
        zscore_res = detect_zscore(df, threshold=zscore_threshold)
        
        metrics = evaluate_models(df, stl_res, iforest_res, zscore_res)
        return metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/pr-curve")
def get_pr_curve():
    try:
        df = load_daily_costs(CSV_PATH)
        y_true = df['anomaly/IsAnomaly'].values
        
        # 1. STL curve
        stl_curve = []
        # threshold multipliers from 1.0 to 6.0 in steps of 0.4
        for thresh in np.arange(1.0, 6.2, 0.4):
            res = detect_stl(df, threshold_multiplier=thresh)
            y_pred = res['anomaly_stl'].values
            
            tp = np.sum((y_true == 1) & (y_pred == 1))
            fp = np.sum((y_true == 0) & (y_pred == 1))
            fn = np.sum((y_true == 1) & (y_pred == 0))
            
            precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 1.0
            recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
            
            stl_curve.append({
                "threshold": round(float(thresh), 1),
                "precision": precision,
                "recall": recall
            })
            
        # 2. Z-Score curve
        z_curve = []
        # threshold from 1.0 to 5.0 in steps of 0.4
        for thresh in np.arange(1.0, 5.2, 0.4):
            res = detect_zscore(df, threshold=thresh)
            y_pred = res['anomaly_zscore'].values
            
            tp = np.sum((y_true == 1) & (y_pred == 1))
            fp = np.sum((y_true == 0) & (y_pred == 1))
            fn = np.sum((y_true == 1) & (y_pred == 0))
            
            precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 1.0
            recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
            
            z_curve.append({
                "threshold": round(float(thresh), 1),
                "precision": precision,
                "recall": recall
            })
            
        return {
            "STL": stl_curve,
            "ZScore": z_curve
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/inject")
def inject_anomaly(req: AnomalyInjectionRequest):
    try:
        # Validate date format
        datetime.strptime(req.date, "%Y-%m-%d")
        
        services = ['AmazonEC2', 'AmazonRDS', 'AmazonS3', 'AmazonDynamoDB', 'AWSDataTransfer']
        if req.service not in services:
            raise HTTPException(status_code=400, detail=f"Service must be one of {services}")
            
        success = inject_dynamic_anomaly(
            CSV_PATH, 
            req.date, 
            req.service, 
            req.spike_amount, 
            req.reason
        )
        
        if success:
            return {"status": "success", "message": f"Successfully injected anomaly on {req.date}."}
        else:
            raise HTTPException(status_code=404, detail="Requested date not found in active cost timeline.")
            
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/reset")
def reset_data():
    try:
        generate_synthetic_cur(output_path=CSV_PATH)
        return {"status": "success", "message": "Synthetic database reset to original base values."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount Frontend static files
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend"))
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
else:
    print(f"Warning: Frontend static directory not found at {frontend_dir}. API will run without UI hosting.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
