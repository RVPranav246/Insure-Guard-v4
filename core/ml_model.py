import pandas as pd
import numpy as np
import lightgbm as lgb
import pickle
import os
from sklearn.model_selection import train_test_split
from sklearn.metrics import (accuracy_score, f1_score,
                             classification_report, confusion_matrix,
                             roc_auc_score)

FEATURES = [
    "Vehicle Age (Yrs)", "Report Delay (Days)", "Claim Amount (₹)",
    "Benchmark (₹)", "Claim/Benchmark %", "Claims 90d", "Claims Total",
    "Rejected", "WS Fraud %", "Contact Overlap", "Approved?",
    "Claim Type", "Segment", "Injury", "Police Report"
]
TARGET = "Fraud (0/1)"
MODEL_PATH = os.path.join(os.path.dirname(__file__), "lgbm_model.pkl")

_CLAIM_TYPES = ["Fire Damage", "Major Accident", "Minor Scratch/Dent",
                "Moderate Collision", "Natural Disaster", "Third Party Liability",
                "Theft/Total Loss", "Windshield/Glass"]
_SEGMENTS    = ["Hatchback", "MUV", "SUV", "Sedan"]


def _preprocess(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Contact Overlap"] = (df["Contact Overlap"] == "Yes").astype(int)
    df["Approved?"]       = (df["Approved?"] == "Yes").astype(int)
    df["Injury"]          = (df["Injury"] == "Yes").astype(int)
    df["Police Report"]   = df["Police Report"].apply(
        lambda x: 1 if str(x).strip().lower() == "yes" else 0
    )
    df["Claim Type"] = df["Claim Type"].apply(
        lambda x: _CLAIM_TYPES.index(x) if x in _CLAIM_TYPES else 0
    )
    df["Segment"] = df["Segment"].apply(
        lambda x: _SEGMENTS.index(x) if x in _SEGMENTS else 0
    )
    return df[FEATURES]


def train_model(dataset_path: str):
    df = pd.read_excel(dataset_path, sheet_name="Claims_Data")
    X  = _preprocess(df)
    y  = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42, stratify=y
    )

    # Constrained settings to prevent overfitting on synthetic data
    model = lgb.LGBMClassifier(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=3,
        num_leaves=8,
        min_child_samples=30,
        subsample=0.7,
        colsample_bytree=0.7,
        reg_alpha=1.0,
        reg_lambda=2.0,
        class_weight="balanced",
        random_state=42,
        verbose=-1,
    )
    model.fit(X_train, y_train)

    y_pred  = model.predict(X_test)
    y_prob  = model.predict_proba(X_test)[:, 1]

    acc    = accuracy_score(y_test, y_pred)
    f1     = f1_score(y_test, y_pred)
    roc    = roc_auc_score(y_test, y_prob)
    cm     = confusion_matrix(y_test, y_pred)

    print("=" * 45)
    print("       InsureGuard — LightGBM Results")
    print("=" * 45)
    print(f"Accuracy  : {acc:.2%}")
    print(f"F1 Score  : {f1:.2%}")
    print(f"ROC-AUC   : {roc:.2%}")
    print()
    print(classification_report(y_test, y_pred,
                                 target_names=["Legit", "Fraud"]))
    print("Confusion Matrix:")
    print(f"  True Legit  (correct): {cm[0][0]}")
    print(f"  False Fraud (missed) : {cm[0][1]}")
    print(f"  False Legit (wrong)  : {cm[1][0]}")
    print(f"  True Fraud  (caught) : {cm[1][1]}")
    print("=" * 45)

    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    print(f"Model saved → {MODEL_PATH}")
    return model


def _encode_claim_type(ct):
    return _CLAIM_TYPES.index(ct) if ct in _CLAIM_TYPES else 0


def _encode_segment(s):
    return _SEGMENTS.index(s) if s in _SEGMENTS else 0


def predict_fraud(claim: dict) -> dict:
    if not os.path.exists(MODEL_PATH):
        return {
            "ml_score": None,
            "ml_probability": None,
            "ml_verdict": "Model not trained",
            "error": "Run train.py first to generate lgbm_model.pkl"
        }

    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)

    row = {
        "Vehicle Age (Yrs)":   claim.get("vehicle_age", 0),
        "Report Delay (Days)": claim.get("report_delay", 0),
        "Claim Amount (₹)":    claim.get("claim_amount", 0),
        "Benchmark (₹)":       claim.get("benchmark", 0),
        "Claim/Benchmark %":   claim.get("cb_percent", 0),
        "Claims 90d":          claim.get("claims_90d", 0),
        "Claims Total":        claim.get("claims_total", 0),
        "Rejected":            claim.get("rejected", 0),
        "WS Fraud %":          claim.get("ws_fraud_pct", 0),
        "Contact Overlap":     1 if claim.get("contact_overlap") == "Yes" else 0,
        "Approved?":           1 if claim.get("ws_approved") == "Yes" else 0,
        "Claim Type":          _encode_claim_type(claim.get("claim_type", "")),
        "Segment":             _encode_segment(claim.get("segment", "")),
        "Injury":              1 if claim.get("injury") == "Yes" else 0,
        "Police Report":       1 if claim.get("police_report") == "Yes" else 0,
    }

    df   = pd.DataFrame([row])
    prob = model.predict_proba(df)[0][1]
    label = model.predict(df)[0]

    return {
        "ml_probability": round(float(prob), 4),
        "ml_score":       int(round(prob * 100)),
        "ml_verdict":     "Fraud" if label == 1 else "Legitimate",
        "error":          None,
    }
