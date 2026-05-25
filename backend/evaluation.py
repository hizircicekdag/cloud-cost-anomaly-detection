import numpy as np

def calculate_metrics(y_true, y_pred):
    """
    Computes Precision, Recall, F1-Score, and Confusion Matrix values.
    """
    y_true = np.array(y_true)
    y_pred = np.array(y_pred)
    
    tp = np.sum((y_true == 1) & (y_pred == 1))
    fp = np.sum((y_true == 0) & (y_pred == 1))
    fn = np.sum((y_true == 1) & (y_pred == 0))
    tn = np.sum((y_true == 0) & (y_pred == 0))
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1_score = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / len(y_true) if len(y_true) > 0 else 0.0
    
    return {
        "precision": float(precision),
        "recall": float(recall),
        "f1_score": float(f1_score),
        "accuracy": float(accuracy),
        "tp": int(tp),
        "fp": int(fp),
        "fn": int(fn),
        "tn": int(tn)
    }

def evaluate_models(df_daily, stl_results, iforest_results, zscore_results):
    """
    Evaluates the three anomaly detection methods against ground truth labels.
    """
    y_true = df_daily['anomaly/IsAnomaly'].values
    
    stl_metrics = calculate_metrics(y_true, stl_results['anomaly_stl'].values)
    iforest_metrics = calculate_metrics(y_true, iforest_results['anomaly_iforest'].values)
    zscore_metrics = calculate_metrics(y_true, zscore_results['anomaly_zscore'].values)
    
    return {
        "STL": stl_metrics,
        "IsolationForest": iforest_metrics,
        "ZScore": zscore_metrics
    }
