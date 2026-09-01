from __future__ import annotations

import json
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.linear_model import LogisticRegression


APP = Path(__file__).resolve().parents[2]
TRAIN_PATH = APP / "data/action/action_train.json"


class ActionClassifier:
    def __init__(self):
        features = FeatureUnion([
            (
                "word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char",
                    ngram_range=(2, 5),
                    sublinear_tf=True,
                ),
            ),
        ])

        self.model = Pipeline([
            ("features", features),
            (
                "classifier",
                LogisticRegression(
                    max_iter=2000,
                    class_weight="balanced",
                    random_state=42,
                ),
            ),
        ])

    def fit(self, texts, labels):
        self.model.fit(texts, labels)
        return self

    def predict(self, text: str) -> tuple[str, float]:
        probabilities = self.model.predict_proba([text])[0]
        classes = self.model.classes_

        best_index = int(probabilities.argmax())

        return (
            str(classes[best_index]),
            float(probabilities[best_index]),
        )


def _load_classifier() -> ActionClassifier:
    rows = json.loads(
        TRAIN_PATH.read_text(encoding="utf-8")
    )

    classifier = ActionClassifier()
    classifier.fit(
        [row["text"] for row in rows],
        [row["action"] for row in rows],
    )

    return classifier


_CLASSIFIER = _load_classifier()


def classify_action(text: str) -> tuple[str, float]:
    return _CLASSIFIER.predict(text)
