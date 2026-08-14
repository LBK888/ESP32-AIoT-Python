import math
import time

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("ai-01")
except (ImportError, Exception):
    web = None

# These coefficients are a teaching placeholder. Retrain, validate on held-out
# data, and paste both the weights and matching feature normalization here.
MODEL = {
    "bias": -1.2,
    "temp_dev": 0.9,
    "level_drop": 1.4,
    "quality_bad": 1.1,
    "feed_low": 0.7,
    "night_do_risk": 0.8,
}
FEATURE_NAMES = ("temp_dev", "level_drop", "quality_bad", "feed_low", "night_do_risk")
USE_DEMO_FEATURES = True


def sigmoid(x):
    x = min(30, max(-30, x))
    return 1 / (1 + math.exp(-x))


def validate_features(features):
    if not isinstance(features, dict) or any(name not in features for name in FEATURE_NAMES):
        return None
    cleaned = {}
    for name in FEATURE_NAMES:
        try:
            value = float(features[name])
        except (TypeError, ValueError):
            return None
        if not 0.0 <= value <= 5.0:
            return None
        cleaned[name] = value
    return cleaned


def anomaly_probability(features):
    features = validate_features(features)
    if features is None:
        return None
    z = MODEL["bias"] + sum(MODEL[name] * features[name] for name in FEATURE_NAMES)
    return sigmoid(z)


def classify(prob):
    if prob is None:
        return "MISSING"
    if prob >= 0.75:
        return "ALERT"
    if prob >= 0.45:
        return "WARN"
    return "OK"


def read_features():
    if not USE_DEMO_FEATURES:
        # Replace with normalized outputs from chapters 3, 6, 8, 11 and 13.
        return None
    seconds = time.ticks_ms() // 1000 % 120
    return {
        "temp_dev": 0.2 if seconds < 60 else 1.2,
        "level_drop": 0.1,
        "quality_bad": 0.3,
        "feed_low": 0.0 if seconds < 90 else 1.0,
        "night_do_risk": 0.4,
    }


def main():
    last_label = None
    while True:
        features = read_features()
        prob = anomaly_probability(features)
        label = classify(prob)
        status = "missing" if prob is None else "danger" if label == "ALERT" else "warning" if label == "WARN" else "normal"
        print("features={}, anomaly_prob={}, label={}".format(features, prob, label))
        if web:
            web.send_readings([
                {"metric": "anomaly_score", "value": None if prob is None else round(prob * 100, 1), "unit": "%", "status": status},
                {"metric": "mode", "value": "demo_features" if USE_DEMO_FEATURES else "live_features", "unit": "", "status": "warning" if USE_DEMO_FEATURES else status},
            ], {"chapter": 15, "demo": USE_DEMO_FEATURES, "features": features or {}})
            if label == "ALERT" and label != last_label:
                web.send_event("anomaly.detected", "danger", "Tiny anomaly model alert", "Inspect raw sensors before acting", {"probability": prob})
        last_label = label
        time.sleep(5)


if __name__ == "__main__":
    main()
