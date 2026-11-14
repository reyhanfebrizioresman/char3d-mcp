"""Default fal.ai model ids and how to build their inputs.

Model ids on fal.ai change over time. Every default can be overridden per call
(`model=`) or globally via environment variables:
    CHAR3D_MODEL_TEXT_TO_IMAGE, CHAR3D_MODEL_IMAGE_TO_3D,
    CHAR3D_MODEL_IMAGE_TO_VIDEO, CHAR3D_MODEL_TEXT_TO_VIDEO
Check the model's page on fal.ai for its exact input fields; pass anything extra via
`extra_input`.
"""
import os

DEFAULTS = {
    "text_to_image": "fal-ai/flux/schnell",
    "image_to_3d": "fal-ai/hunyuan3d/v2",
    "image_to_video": "fal-ai/kling-video/v2.1/standard/image-to-video",
    "text_to_video": "fal-ai/kling-video/v2.1/standard/text-to-video",
}

# models whose image input is not called "image_url"
IMAGE_FIELD = {
    "fal-ai/hunyuan3d/v2": "input_image_url",
    "fal-ai/hunyuan3d/v2/mini": "input_image_url",
}

CHARACTER_PROMPT = ("{prompt}. Full body, single character standing in a relaxed A-pose, "
                    "arms slightly away from the body, front view, centered, entire body "
                    "visible, plain light grey background, soft even lighting, 3D render")
PROP_PROMPT = ("{prompt}. Single object, centered, entire object visible, plain light grey "
               "background, soft even lighting, 3D render")


def model_for(kind, override=None):
    if override:
        return override
    return os.environ.get(f"CHAR3D_MODEL_{kind.upper()}") or DEFAULTS[kind]


def image_field(model):
    return IMAGE_FIELD.get(model, "image_url")


def image_to_3d_input(model, image_url, extra=None):
    payload = {image_field(model): image_url}
    payload.update(extra or {})
    return payload


def image_to_video_input(model, image_url, prompt, duration, aspect_ratio=None, extra=None):
    payload = {image_field(model): image_url, "prompt": prompt, "duration": str(int(duration))}
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    payload.update(extra or {})
    return payload


def text_to_video_input(prompt, duration, aspect_ratio="16:9", extra=None):
    payload = {"prompt": prompt, "duration": str(int(duration)), "aspect_ratio": aspect_ratio}
    payload.update(extra or {})
    return payload
