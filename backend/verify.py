import sys
import os
import pandas as pd

# Add the current folder to sys.path to resolve imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from data_generator import generate_synthetic_cur, load_daily_costs
from detector import detect_stl, detect_isolation_forest, detect_zscore, perform_root_cause_attribution
from evaluation import evaluate_models

def run_verification():
    print("=== STARTING CLOUD COST ANOMALY DETECTION TEST SUITE ===")
    
    csv_path = "aws_cur_synthetic.csv"
    
    # 1. Test data generation
    print("\n[Test 1/4] Verifying Data Generator...")
    if os.path.exists(csv_path):
        os.remove(csv_path)
    
    df_raw = generate_synthetic_cur(output_path=csv_path)
    assert len(df_raw) > 0, "Raw CUR data should not be empty."
    assert "lineItem/ProductCode" in df_raw.columns, "ProductCode column missing."
    assert "lineItem/UnblendedCost" in df_raw.columns, "UnblendedCost column missing."
    print("✓ Data generation success! Raw records generated:", len(df_raw))
    
    # 2. Test daily aggregated costs loader
    df_daily = load_daily_costs(csv_path)
    assert len(df_daily) == 180, f"Expected 180 daily aggregations, got {len(df_daily)}"
    assert "TotalCost" in df_daily.columns, "TotalCost aggregation missing."
    assert "anomaly/IsAnomaly" in df_daily.columns, "Ground truth anomaly column missing."
    print("✓ Daily aggregation loader success! Unique days loaded:", len(df_daily))
    
    # 3. Test Detectors
    print("\n[Test 2/4] Running Anomaly Detection Modules...")
    
    # STL
    stl_res = detect_stl(df_daily)
    assert len(stl_res) == len(df_daily), "STL result size mismatch."
    assert "anomaly_stl" in stl_res.columns, "STL anomaly flags missing."
    print(f"✓ STL Decomposition run complete. Detected {stl_res['anomaly_stl'].sum()} anomalies.")
    
    # Isolation Forest
    iforest_res = detect_isolation_forest(df_daily)
    assert len(iforest_res) == len(df_daily), "Isolation Forest result size mismatch."
    assert "anomaly_iforest" in iforest_res.columns, "IForest flags missing."
    print(f"✓ Isolation Forest run complete. Detected {iforest_res['anomaly_iforest'].sum()} anomalies.")
    
    # Z-Score
    zscore_res = detect_zscore(df_daily)
    assert len(zscore_res) == len(df_daily), "Z-score result size mismatch."
    assert "anomaly_zscore" in zscore_res.columns, "Z-score flags missing."
    print(f"✓ Rolling Z-score run complete. Detected {zscore_res['anomaly_zscore'].sum()} anomalies.")
    
    # 4. Test Root Cause Analysis
    print("\n[Test 3/4] Running Root-Cause Attribution engine...")
    # Find day index 30 (our first EC2 leak ground-truth anomaly)
    anomaly_dates = df_daily[df_daily['anomaly/IsAnomaly'] == 1].index
    if len(anomaly_dates) > 0:
        target_date = anomaly_dates[0]
        attribution = perform_root_cause_attribution(df_daily, target_date, ["STL", "Z-Score"])
        print(f"Attributing anomaly on {target_date.strftime('%Y-%m-%d')}:")
        print(f"  Primary Suspect: {attribution['primary_service']}")
        print(f"  Confidence: {attribution['confidence']}")
        print(f"  Explanation: {attribution['root_cause_explanation']}")
        
        assert attribution["primary_service"] == "AmazonEC2", "Expected first ground truth anomaly to attribute to AmazonEC2"
        print("✓ Root-Cause attribution verified successfully.")
    else:
        print("⚠ Warning: No ground truth anomalies found for attribution testing.")
        
    # 5. Test Evaluator
    print("\n[Test 4/4] Verifying Evaluation Metrics calculation...")
    metrics = evaluate_models(df_daily, stl_res, iforest_res, zscore_res)
    for model_name, score in metrics.items():
        print(f"  {model_name}: Precision={score['precision']:.3f}, Recall={score['recall']:.3f}, F1-Score={score['f1_score']:.3f}")
        assert 0.0 <= score["precision"] <= 1.0, f"Invalid precision value: {score['precision']}"
        assert 0.0 <= score["recall"] <= 1.0, f"Invalid recall value: {score['recall']}"
        assert 0.0 <= score["f1_score"] <= 1.0, f"Invalid f1_score value: {score['f1_score']}"
        
    print("✓ Model evaluation metrics verified successfully.")
    print("\n=== ALL TESTS PASSED SUCCESSFULLY! ===")
    
if __name__ == "__main__":
    run_verification()
