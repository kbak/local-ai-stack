"""Model-visible tools; trusted conversation context lives in image_tools."""
from strands import tool
from image_tools import run_image


@tool
async def generate_image(prompt: str, size: str = "1024x1024") -> str:
    """Create a new image and send it to the current Signal conversation.

    Args:
        prompt: Detailed description of the requested image.
        size: 1024x1024 (square), 768x1024 (portrait), or 1024x768 (landscape).
    """
    return await run_image(prompt, size)


@tool
async def edit_image(prompt: str, image_id: str = "latest", size: str = "1024x1024") -> str:
    """Edit an uploaded or previously generated image and send the result to Signal.

    Args:
        prompt: Requested changes and details that should remain unchanged.
        image_id: Image reference ID supplied in conversation, or latest. Never a path or URL.
        size: 1024x1024 (square), 768x1024 (portrait), or 1024x768 (landscape).
    """
    return await run_image(prompt, size, image_id)
