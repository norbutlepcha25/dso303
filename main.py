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

    # ---------------------------------------------------------
    # House-style figure and embed (preferred for new content)
    #
    # Both print one line of HTML, so they work at any indentation,
    # including inside admonitions and ??? accordions. Step-by-step
    # usage: utils/media-components.md. utils/image_audit.py checks them.
    # ---------------------------------------------------------
    import html as _html
    import re as _re

    def _source_line(label, source, source_url):
        text = _html.escape(source or "Unknown")
        if source_url:
            text = (
                f'<a href="{_html.escape(source_url, quote=True)}" '
                f'target="_blank" rel="noopener">{text}</a>'
            )
        return (
            "<p align='right' style=\"font-size:0.8em\">"
            f"<i>{label} Source: {text}</i></p>"
        )

    @env.macro
    def figure(src, caption, source, alt="", source_url="", width="80%"):
        """
        An image in the house figure style: image, caption, source line.

        src         path relative to the Markdown file, as for ![...](...)
        caption     short title, no "Figure:" prefix, no full stop
        source      e.g. "AI generated (ChatGPT)", "Created by the author",
                    "AWS Architecture Icons"
        alt         what the image shows, for screen readers
        source_url  optional link for the source text
        width       CSS width, default "80%"

        Example:
            {{ figure("../img/U5/t1/build-once-deploy-many.png",
                      "Build Once, Deploy Many",
                      "AI generated (Google Gemini)",
                      alt="One commit built once and deployed to three environments") }}
        """
        return (
            '<figure class="dso-figure">'
            f'<img src="{_html.escape(src, quote=True)}" '
            f'alt="{_html.escape(alt or caption, quote=True)}" '
            f'style="width:{_html.escape(width, quote=True)}" loading="lazy">'
            f"<figcaption>{_html.escape(caption)}</figcaption>"
            f"{_source_line('Image', source, source_url)}"
            "</figure>"
        )

    @env.macro
    def embed(url, caption, source, source_url="", height="600px", intro=""):
        """
        A YouTube video or any web page in an iframe, with caption and source.

        url         YouTube watch/short/youtu.be URL (a t= start time is kept),
                    or any https page that allows embedding
        caption     short title, as for figure()
        source      e.g. "ByteMonk, YouTube" or "AWS Documentation"
        source_url  optional; defaults to url
        height      iframe height for non-YouTube pages (videos are 16:9)
        intro       optional lead-in sentence shown above the video; it is
                    part of the component, so it disappears from the PDF
                    together with the video

        Videos and embedded pages never appear in the PDF: print.css hides
        figure.dso-embed and utils/build_pdfs.py removes it before printing.

        Example:
            {{ embed("https://www.youtube.com/watch?v=RThb3koc5DM",
                     "Software Deployment Strategies",
                     "ByteMonk, YouTube") }}
        """
        title = _html.escape(caption, quote=True)
        yt = _re.search(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})", url)
        if yt:
            start = _re.search(r"[?&#](?:t|start)=(\d+)", url)
            src = f"https://www.youtube-nocookie.com/embed/{yt.group(1)}"
            if start:
                src += f"?start={start.group(1)}"
            frame = (
                '<div class="youtube-wrapper">'
                f'<iframe src="{src}" title="{title}" loading="lazy" '
                'allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
                'referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe></div>'
            )
            label = "Video"
        else:
            frame = (
                '<div class="external-site-container">'
                f'<iframe src="{_html.escape(url, quote=True)}" title="{title}" '
                f'style="min-height:0;height:{_html.escape(height, quote=True)}" '
                'loading="lazy" allowfullscreen></iframe></div>'
            )
            label = "Content"
        lead = f'<p class="dso-embed-intro">{_html.escape(intro)}</p>' if intro else ""
        return (
            '<figure class="dso-embed">'
            f"{lead}{frame}"
            f"<figcaption>{_html.escape(caption)}</figcaption>"
            f"{_source_line(label, source, source_url or url)}"
            "</figure>"
        )
