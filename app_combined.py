import os
import time
import json
from threading import Lock

from PIL import Image

import cv2
import gradio as gr
import numpy as np
import tensorflow as tf


# ============================================================
# CONFIGURATION
# ============================================================

MODEL_WEIGHTS_PATH = "checkpoint.weights.h5"

TARGET_FRAMES = 75
FRAME_HEIGHT = 46
FRAME_WIDTH = 140

# Medicinal plant model files (place these in the Space repository root).
MEDICINAL_MODEL_PATH = "medicinal_model.keras"
MEDICINAL_LABELS_PATH = "class_indices.json"
MEDICINAL_IMG_SIZE = (224, 224)

# Lazy-loaded: the medicinal model is loaded only when its button/API is used.
# It remains in memory afterward so subsequent predictions are faster.
_medicinal_model = None
_medicinal_class_names = None
_medicinal_load_lock = Lock()


# ============================================================
# VOCABULARY
# Must remain identical to the trained model
# ============================================================

vocab = [
    x for x in "abcdefghijklmnopqrstuvwxyz0123456789'?! "
]

char_to_num = tf.keras.layers.StringLookup(
    vocabulary=vocab,
    oov_token=""
)

num_to_char = tf.keras.layers.StringLookup(
    vocabulary=char_to_num.get_vocabulary(),
    oov_token="",
    invert=True
)


# ============================================================
# MODEL ARCHITECTURE
#
# IMPORTANT:
# This is inference only.
# No training is performed.
# ============================================================

def build_model():

    inputs = tf.keras.layers.Input(
        shape=(
            TARGET_FRAMES,
            FRAME_HEIGHT,
            FRAME_WIDTH,
            1
        ),
        name="input"
    )

    x = tf.keras.layers.Conv3D(
        128,
        3,
        padding="same",
        activation="relu"
    )(inputs)

    x = tf.keras.layers.MaxPool3D(
        pool_size=(1, 2, 2)
    )(x)

    x = tf.keras.layers.Conv3D(
        256,
        3,
        padding="same",
        activation="relu"
    )(x)

    x = tf.keras.layers.MaxPool3D(
        pool_size=(1, 2, 2)
    )(x)

    x = tf.keras.layers.Conv3D(
        75,
        3,
        padding="same",
        activation="relu"
    )(x)

    x = tf.keras.layers.MaxPool3D(
        pool_size=(1, 2, 2)
    )(x)

    x = tf.keras.layers.Reshape(
        (TARGET_FRAMES, -1)
    )(x)

    x = tf.keras.layers.Bidirectional(
        tf.keras.layers.LSTM(
            128,
            return_sequences=True
        )
    )(x)

    x = tf.keras.layers.Dropout(0.5)(x)

    x = tf.keras.layers.Bidirectional(
        tf.keras.layers.LSTM(
            128,
            return_sequences=True
        )
    )(x)

    x = tf.keras.layers.Dropout(0.5)(x)

    outputs = tf.keras.layers.Dense(
        len(char_to_num.get_vocabulary()),
        activation="softmax"
    )(x)

    return tf.keras.Model(
        inputs,
        outputs
    )


# ============================================================
# LOAD MODEL ONCE
# ============================================================

print("============================================")
print("MouthMap Inference Service")
print("============================================")
print("Loading model...")

if not os.path.exists(MODEL_WEIGHTS_PATH):
    raise FileNotFoundError(
        f"Model checkpoint not found: "
        f"{MODEL_WEIGHTS_PATH}"
    )

model = build_model()

model.load_weights(
    MODEL_WEIGHTS_PATH
)

print("MouthMap model loaded successfully.")
print(
    f"Input shape: {model.input_shape}"
)


# ============================================================
# VIDEO PREPROCESSING
#
# Verbatim parity with the original MouthMap Streamlit pipeline
# (the reference implementation). DO NOT "improve" this:
#
#   * frame sampling: np.linspace(0, total-1, 75, dtype=int)
#     membership, pad with the last collected frame;
#   * grayscale: tf.image.rgb_to_grayscale applied to the cv2
#     BGR frame. TensorFlow weights [0.2989, 0.5870, 0.1140]
#     are applied to channels in stored order (B, G, R), so
#     this is NOT the same as cv2.COLOR_BGR2GRAY
#     (which uses 0.114*B + 0.587*G + 0.299*R). The trained
#     model expects the TensorFlow variant;
#   * fixed crop: frame[190:236, 80:220, :] (46 rows x 140 cols);
#   * normalization: mean over the uint8 stack, std over the
#     float32-cast stack, subtract in the stack dtype, cast,
#     divide (copied verbatim below);
#   * tensor shape: (1, 75, 46, 140, 1).
#
# The error guards (isOpened, empty video, no usable frames)
# and the std floor below are the ONLY intentional additions:
# they only trigger on corrupt/degenerate input that the
# original code would crash on.
# ============================================================

def load_video(
    path: str,
    target_frames: int = TARGET_FRAMES
):

    cap = cv2.VideoCapture(path)

    if not cap.isOpened():
        raise ValueError(
            "Unable to open video."
        )

    frames = []

    total_frames = int(
        cap.get(cv2.CAP_PROP_FRAME_COUNT)
    )

    if total_frames <= 0:
        cap.release()

        raise ValueError(
            "Video contains no readable frames."
        )

    frame_indices = np.linspace(
        0,
        total_frames - 1,
        target_frames,
        dtype=int
    )

    frame_indices = set(
        frame_indices.tolist()
    )

    for i in range(total_frames):

        ret, frame = cap.read()

        if not ret:
            break

        if i in frame_indices:

            # EXACT original behavior: TensorFlow grayscale on the
            # cv2 BGR frame (see module note above). Output is
            # uint8 with shape (H, W, 1).
            frame = tf.image.rgb_to_grayscale(
                frame
            )

            # Fixed MouthMap crop (same as original).
            frame = frame[
                190:236,
                80:220,
                :
            ]

            frames.append(frame)

    cap.release()

    if not frames:
        raise ValueError(
            "No usable video frames found."
        )

    # Pad if necessary (same as original: repeat last frame).
    while len(frames) < target_frames:
        frames.append(frames[-1])

    frames = tf.stack(
        frames[:target_frames]
    )

    # Verbatim original normalization.
    mean = tf.math.reduce_mean(
        frames
    )

    std = tf.math.reduce_std(
        tf.cast(frames, tf.float32)
    )

    # Safety guard (NOT in the original): prevents division by
    # zero on degenerate constant videos. Verified inert on real
    # test videos (their std is ~30-60, far above 1e-6).
    std = tf.maximum(std, 1e-6)

    frames = tf.cast(
        (frames - mean),
        tf.float32
    ) / std

    # Add batch dimension.
    frames = tf.expand_dims(
        frames,
        axis=0
    )

    return frames


# ============================================================
# TEXT CLEANUP
# ============================================================

def clean_prediction(
    predicted_text: str
):

    return " ".join(
        predicted_text
        .replace("!", " ")
        .split()
    )


# ============================================================
# INFERENCE
# ============================================================

def predict_video(
    video_path: str
):

    start_time = time.perf_counter()

    video_input = load_video(
        video_path
    )

    preprocessing_complete = (
        time.perf_counter()
    )

    yhat = model.predict(
        video_input,
        verbose=0
    )

    inference_complete = (
        time.perf_counter()
    )

    # CTC greedy decoding
    decoded = tf.keras.backend.ctc_decode(
        yhat,
        input_length=[
            TARGET_FRAMES
        ],
        greedy=True
    )[0][0].numpy()

    predicted_text = (
        tf.strings.reduce_join(
            num_to_char(decoded)
        )
        .numpy()
        .decode("utf-8")
    )

    predicted_text = clean_prediction(
        predicted_text
    )

    total_time_ms = (
        time.perf_counter()
        - start_time
    ) * 1000

    inference_time_ms = (
        inference_complete
        - preprocessing_complete
    ) * 1000

    preprocessing_time_ms = (
        preprocessing_complete
        - start_time
    ) * 1000

    return {
        "status": "completed",

        "prediction": predicted_text,

        "model": "MouthMap",

        "model_version": "checkpoint.weights.h5",

        "frames_processed": TARGET_FRAMES,

        "input_shape": [
            TARGET_FRAMES,
            FRAME_HEIGHT,
            FRAME_WIDTH,
            1
        ],

        "preprocessing": {
            "grayscale": True,
            "crop": {
                "height": FRAME_HEIGHT,
                "width": FRAME_WIDTH
            },
            "normalization": "mean_std"
        },

        "timing": {
            "preprocessing_ms": round(
                preprocessing_time_ms,
                2
            ),
            "inference_ms": round(
                inference_time_ms,
                2
            ),
            "total_ms": round(
                total_time_ms,
                2
            )
        }
    }


# ============================================================
# API FUNCTION
#
# Contract (Gradio 6.29.1, verified via /gradio_api/info):
#   endpoint /predict, single parameter named `video`,
#   component gr.Video, python_type filepath, queue enabled.
#
# Valid raw-HTTP body:
#   {"video": {"path": "</gradio_api/upload path>",
#              "meta": {"_type": "gradio.FileData"}}}
# A body of {"data": [...]} is REJECTED with:
#   Parameter `data` is not a valid key-word argument.
# ============================================================

# Temporary input-contract logging. Disable after verification:
#   MOUTHMAP_DEBUG_INPUT=0
DEBUG_INPUT = os.environ.get(
    "MOUTHMAP_DEBUG_INPUT",
    "1"
) == "1"

# Extensions the OpenCV/FFmpeg build is expected to demux.
# Used only for a sanity warning, never for conversion.
REASONABLE_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".mpg",
    ".mpeg",
    ".mov",
    ".mkv",
    ".avi",
}


def resolve_video_path(video):
    """
    Resolve the Gradio video input to a server-side filepath.

    gr.Video (type="filepath") normally supplies a plain string,
    but FileData dicts/objects are resolved defensively.
    Never logs or returns video bytes.
    """

    if DEBUG_INPUT:
        print(f"input type: {type(video).__name__}")

    if video is None:
        raise ValueError(
            "No video was provided."
        )

    if isinstance(video, str):
        if DEBUG_INPUT:
            print(f"input path: {video}")
        return video

    if isinstance(video, dict):
        path = video.get("path")
        if not path and isinstance(video.get("video"), dict):
            path = video["video"].get("path")
        if path:
            if DEBUG_INPUT:
                print(f"input path: {path}")
            return path
        raise ValueError(
            "Video reference is missing its server path."
        )

    path = getattr(video, "path", None)
    if path:
        if DEBUG_INPUT:
            print(f"input path: {path}")
        return path

    raise ValueError(
        "Unsupported video input type: "
        f"{type(video).__name__}"
    )


def validate_video_file(path: str):
    """
    Fail fast on corrupt/truncated/wrong-object uploads BEFORE
    load_video()/model.predict(). Logs safe diagnostics only.
    """

    filename = os.path.basename(path)
    extension = os.path.splitext(filename)[1].lower()

    if not os.path.exists(path) or not os.path.isfile(path):
        raise ValueError(
            "Uploaded video file is missing on the server."
        )

    size = os.path.getsize(path)
    if size <= 0:
        raise ValueError(
            "Uploaded video is empty."
        )

    if (
        extension
        and extension not in REASONABLE_EXTENSIONS
    ):
        print(
            "mouthmap warning: unexpected video extension "
            f"{extension} for file {filename}; "
            "attempting to open anyway."
        )

    cap = cv2.VideoCapture(path)
    opened = cap.isOpened()

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    print(
        "mouthmap video: "
        f"filename={filename} "
        f"extension={extension or '(none)'} "
        f"size={size} "
        f"path={path} "
        f"opened={opened} "
        f"frames={frame_count} "
        f"{width}x{height} "
        f"fps={fps}"
    )

    if not opened:
        cap.release()
        raise ValueError(
            "Uploaded video is invalid, incomplete, "
            "or unsupported."
        )

    ret, _ = cap.read()
    cap.release()

    if not ret:
        raise ValueError(
            "Uploaded video contains no readable frames."
        )


def mouthmap_predict(video):
    """
    Run MouthMap inference on a video.

    Returns a JSON-compatible dictionary containing
    the predicted sentence and real inference metadata.
    """

    if video is None:
        return {
            "status": "failed",
            "error": "No video provided."
        }

    try:

        # Resolve Gradio input (str filepath, FileData dict,
        # or object with .path) to a server-side path.
        source_path = resolve_video_path(video)

        # Validate BEFORE any model work. Uses the Gradio
        # server path directly: no re-suffixing, no fake
        # container conversion (a WebM must never be
        # renamed to .mp4 and vice versa).
        validate_video_file(source_path)

        result = predict_video(
            source_path
        )

        return result

    except Exception as exc:

        print(
            f"MouthMap inference error: {exc}"
        )

        return {
            "status": "failed",
            "error": str(exc)
        }



# ============================================================
# MEDICINAL PLANT MODEL - IMAGE INFERENCE
#
# Separate from MouthMap. The original MouthMap architecture,
# preprocessing, decoding and API function above are unchanged.
# The medicinal model is loaded on demand to avoid using its
# memory unless this feature is requested.
# ============================================================

def load_medicinal_resources():
    global _medicinal_model, _medicinal_class_names

    if _medicinal_model is not None and _medicinal_class_names is not None:
        return _medicinal_model, _medicinal_class_names

    with _medicinal_load_lock:
        # Check again after acquiring the lock.
        if _medicinal_model is not None and _medicinal_class_names is not None:
            return _medicinal_model, _medicinal_class_names

        if not os.path.isfile(MEDICINAL_MODEL_PATH):
            raise FileNotFoundError(
                f"Medicinal plant model not found: {MEDICINAL_MODEL_PATH}"
            )

        if not os.path.isfile(MEDICINAL_LABELS_PATH):
            raise FileNotFoundError(
                f"Class-label file not found: {MEDICINAL_LABELS_PATH}. "
                "Upload the class_indices.json file to the Space repository."
            )

        with open(MEDICINAL_LABELS_PATH, "r", encoding="utf-8") as f:
            class_indices = json.load(f)

        if not isinstance(class_indices, dict) or not class_indices:
            raise ValueError(
                "class_indices.json must contain a non-empty "
                "class-name-to-index JSON object."
            )

        # Reconstruct the exact output-neuron order used by training.
        class_names = [
            name for name, index in
            sorted(class_indices.items(), key=lambda item: int(item[1]))
        ]

        print("Loading medicinal plant model...")
        plant_model = tf.keras.models.load_model(
            MEDICINAL_MODEL_PATH,
            compile=False
        )

        output_classes = int(plant_model.output_shape[-1])
        if output_classes != len(class_names):
            del plant_model
            raise ValueError(
                f"Model has {output_classes} output classes, but "
                f"{len(class_names)} labels were found in "
                f"{MEDICINAL_LABELS_PATH}. The label mapping must match "
                "the exact training class order."
            )

        _medicinal_model = plant_model
        _medicinal_class_names = class_names

        print(
            f"Medicinal plant model loaded: {len(class_names)} classes."
        )

    return _medicinal_model, _medicinal_class_names


def predict_medicinal_plant(image):
    """
    Predict one medicinal plant image and return JSON-compatible output.
    Preprocessing matches training: RGB, 224x224, pixel values / 255.
    """

    start_time = time.perf_counter()

    try:
        if image is None:
            raise ValueError("No image was provided.")

        image_path = image
        if isinstance(image_path, dict):
            image_path = image_path.get("path")
        elif hasattr(image_path, "path"):
            image_path = getattr(image_path, "path", image_path)

        if not isinstance(image_path, str) or not image_path:
            raise ValueError("Uploaded image does not contain a valid server filepath.")

        if not os.path.isfile(image_path):
            raise ValueError(f"Uploaded image file was not found on the server: {image_path}")

        model, class_names = load_medicinal_resources()

        preprocess_start = time.perf_counter()

        with Image.open(image_path) as source_image:
            img = source_image.convert("RGB")
            img = img.resize(MEDICINAL_IMG_SIZE)
            img_array = np.asarray(img, dtype=np.float32)

        # Exact normalization used by the medicinal-plant training code.
        img_array = np.expand_dims(img_array, axis=0) / 255.0

        preprocess_end = time.perf_counter()

        predictions = model.predict(img_array, verbose=0)[0]

        inference_end = time.perf_counter()

        top_indices = np.argsort(predictions)[::-1][:5]
        best_index = int(top_indices[0])
        predicted_class = class_names[best_index]
        confidence = float(predictions[best_index]) * 100.0

        if "_" in predicted_class:
            kind, plant_name = predicted_class.split("_", 1)
        else:
            kind, plant_name = "", predicted_class

        plant_type = "Leaf" if kind.lower() == "leaf" else "Plant"
        display_name = (
            f"{plant_name.replace('_', ' ').title()} {plant_type}"
        )

        top_predictions = [
            {
                "rank": rank,
                "class": class_names[int(index)],
                "confidence": round(float(predictions[index]) * 100.0, 2)
            }
            for rank, index in enumerate(top_indices, start=1)
        ]

        total_end = time.perf_counter()

        return {
            "status": "completed",
            "prediction": display_name,
            "predicted_class": predicted_class,
            "plant_name": plant_name.replace("_", " ").title(),
            "plant_type": plant_type,
            "confidence": round(confidence, 2),
            "model": "Medicinal Plant Identifier (VGG16)",
            "model_version": os.path.basename(MEDICINAL_MODEL_PATH),
            "classes_available": len(class_names),
            "input_image": os.path.basename(image_path),
            "input_shape": [224, 224, 3],
            "preprocessing": {
                "color_mode": "RGB",
                "resize": [224, 224],
                "normalization": "pixel_values_divided_by_255"
            },
            "top_5_predictions": top_predictions,
            "timing": {
                "preprocessing_ms": round(
                    (preprocess_end - preprocess_start) * 1000, 2
                ),
                "inference_ms": round(
                    (inference_end - preprocess_end) * 1000, 2
                ),
                "total_ms": round(
                    (total_end - start_time) * 1000, 2
                )
            }
        }

    except Exception as exc:
        print(f"Medicinal plant inference error: {exc}")
        return {
            "status": "failed",
            "error": str(exc),
            "model": "Medicinal Plant Identifier"
        }


# ============================================================
# MINIMAL GRADIO API
#
# No fancy UI.
# This creates the /predict API endpoint.
# ============================================================

with gr.Blocks(
    title="MouthMap + Medicinal Plant Inference"
) as demo:

    gr.Markdown(
        "# AI Inference Hub\\n"
        "Choose one of the two independent models below."
    )

    with gr.Tab("MouthMap - Lip Reading"):
        gr.Markdown(
            "Upload a video or record from your webcam to predict the spoken sentence."
        )

        video_input = gr.Video(
            label="MouthMap Test Video",
            sources=["upload", "webcam"]
        )

        mouthmap_output = gr.JSON(
            label="MouthMap Inference Result"
        )

        mouthmap_button = gr.Button(
            "Run MouthMap Prediction",
            variant="primary"
        )

        # Keep the existing API endpoint name for Revora compatibility.
        mouthmap_button.click(
            fn=mouthmap_predict,
            inputs=video_input,
            outputs=mouthmap_output,
            api_name="predict"
        )

    with gr.Tab("Medicinal Plant Identifier"):
        gr.Markdown(
            "Upload a plant or leaf image to classify it using the trained VGG16 model."
        )

        plant_image_input = gr.Image(
            label="Medicinal Plant / Leaf Image",
            type="filepath"
        )

        plant_output = gr.JSON(
            label="Medicinal Plant Prediction Result"
        )

        plant_button = gr.Button(
            "Identify Medicinal Plant",
            variant="primary"
        )

        plant_button.click(
            fn=predict_medicinal_plant,
            inputs=plant_image_input,
            outputs=plant_output,
            api_name="predict_medicinal_plant"
        )


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    demo.launch()