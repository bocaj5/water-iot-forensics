"""
Standalone TFLite converter for the LSTM autoencoder.

Workaround for TF 2.16 MLIR bug:
  "missing attribute 'value'" / "Failed to infer result type(s)"

TFLiteConverter.from_keras_model() internally saves to SavedModel and converts
via MLIR, which trips on stateful LSTM while-body ops. Using a concrete function
with a fixed input signature bypasses the MLIR rewrite that causes the crash.

Usage:
    python3 -m ml.convert_lstm [--model ml/models/lstm_autoencoder.keras]
                               [--output ml/models/lstm_autoencoder.tflite]
                               [--seq-len 50]
"""

import argparse
import pathlib
import tensorflow as tf


def convert(keras_path: pathlib.Path, out_path: pathlib.Path, seq_len: int) -> None:
    print(f"Loading {keras_path} ...")
    model = tf.keras.models.load_model(keras_path)

    # Pin the batch dimension to 1 (inference-time: one window at a time).
    # from_concrete_functions skips the MLIR while-loop rewrite that crashes.
    @tf.function(
        input_signature=[tf.TensorSpec(shape=[1, seq_len, 1], dtype=tf.float32)]
    )
    def serving_fn(x):
        return model(x, training=False)

    cf = serving_fn.get_concrete_function()
    converter = tf.lite.TFLiteConverter.from_concrete_functions([cf], model)
    converter.optimizations = []          # float32, no quantisation

    print("Converting to TFLite ...")
    tflite_model = converter.convert()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(tflite_model)
    print(f"Saved {out_path}  ({len(tflite_model) / 1024:.1f} KB)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",   default="ml/models/lstm_autoencoder.keras")
    parser.add_argument("--output",  default="ml/models/lstm_autoencoder.tflite")
    parser.add_argument("--seq-len", type=int, default=50)
    args = parser.parse_args()

    convert(pathlib.Path(args.model), pathlib.Path(args.output), args.seq_len)


if __name__ == "__main__":
    main()
