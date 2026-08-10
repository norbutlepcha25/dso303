def define_env(env):
    """
    Define custom macros for MkDocs.
    """

    # ---------------------------------------------------------
    # H5P / Lumi HTML Embed
    # ---------------------------------------------------------
    @env.macro
    def h5p_lumi_embed(
        container_id,
        html_path,
        width="100%",
        height="600px",
        base_url=None
    ):
        """
        Embed a locally hosted H5P/Lumi HTML file.

        Example:
            {{ h5p_lumi_embed(
                "h5p1",
                "h5p/lesson1/index.html"
            ) }}
        """

        if base_url is None:
            base_url = env.config.get("extra", {}).get("base_url", "")

        full_path = (
            f"{base_url}/{html_path.lstrip('/')}"
            if base_url
            else f"/{html_path.lstrip('/')}"
        )

        return f"""
        <div class="embedded-content">
            <iframe
                id="{container_id}"
                src="{full_path}"
                width="{width}"
                height="{height}"
                frameborder="0"
                allowfullscreen
                loading="lazy">
            </iframe>
        </div>
        """

    # ---------------------------------------------------------
    # Image Block
    # ---------------------------------------------------------
    @env.macro
    def image_block(
        src,
        alt_text="",
        caption="",
        source_text="",
        source_url="",
        size="medium",
        width=None
    ):
        """
        Create a formatted image block.

        Example:
            {{ image_block(
                "images/aws.png",
                "AWS Architecture",
                "AWS architecture diagram"
            ) }}
        """

        size_map = {
            "small": "40%",
            "medium": "60%",
            "large": "80%"
        }

        img_width = width if width else size_map.get(size, "60%")

        html = f"""
        <figure class="image-block" style="text-align: center;">
            <img
                src="{src}"
                alt="{alt_text}"
                style="width: {img_width}; max-width: 100%; height: auto;"
                loading="lazy">
        """

        if caption:
            html += f"""
            <figcaption>
                {caption}
            </figcaption>
            """

        if source_text and source_url:
            html += f"""
            <div class="image-source">
                Source:
                <a href="{source_url}" target="_blank" rel="noopener">
                    {source_text}
                </a>
            </div>
            """

        html += """
        </figure>
        """

        return html

    # ---------------------------------------------------------
    # YouTube Embed
    # ---------------------------------------------------------
    @env.macro
    def youtube_embed(
        video,
        title="",
        width="100%",
        align="center"
    ):
        """
        Embed a responsive YouTube video.

        Accepts:
        - Full YouTube URLs
        - youtu.be URLs
        - /embed/ URLs
        - 11-character YouTube video IDs

        Example:
            {{ youtube_embed(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "Example Video"
            ) }}
        """

        import re

        pattern = r"(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})"

        match = re.search(pattern, video)

        video_id = match.group(1) if match else video.strip()

        align_style = (
            "text-align:center;"
            if align == "center"
            else f"text-align:{align};"
        )

        html = f"""
        <div
            class="youtube-container"
            style="{align_style}"
        >
            <div class="youtube-wrapper">
                <iframe
                    src="https://www.youtube.com/embed/{video_id}"
                    title="{title}"
                    frameborder="0"
                    allow="
                        accelerometer;
                        autoplay;
                        clipboard-write;
                        encrypted-media;
                        gyroscope;
                        picture-in-picture;
                        web-share
                    "
                    allowfullscreen
                    loading="lazy">
                </iframe>
            </div>
        </div>
        """

        return html

    # ---------------------------------------------------------
    # Generic External Website Embed
    # ---------------------------------------------------------
    @env.macro
    def iframe_embed(
        url,
        title="Embedded Content",
        width="100%",
        height="700px",
        allowfullscreen=True
    ):
        """
        Embed an external webpage inside an iframe.

        Example:

            {{ iframe_embed(
                "https://example.com",
                "Example Website"
            ) }}

        Parameters:
            url:
                Full URL of the webpage.

            title:
                Accessible title for the iframe.

            width:
                Width of the iframe.

            height:
                Height of the iframe.

            allowfullscreen:
                Whether fullscreen mode is allowed.
        """

        fullscreen = "allowfullscreen" if allowfullscreen else ""

        return f"""
        <div class="external-site-container">
            <iframe
                src="{url}"
                title="{title}"
                width="{width}"
                height="{height}"
                frameborder="0"
                loading="lazy"
                {fullscreen}>
            </iframe>
        </div>
        """