def define_env(env):
    """
    Define custom macros for MkDocs
    """

    @env.macro
    def h5p_lumi_embed(container_id, html_path, width="100%", height="600px", base_url=None):
        if base_url is None:
            base_url = env.config.get('extra', {}).get('base_url', '')
        full_path = f"{base_url}/{html_path.lstrip('/')}" if base_url else f"/{html_path.lstrip('/')}"
        return f'<iframe id="{container_id}" src="{full_path}" width="{width}" height="{height}" frameborder="0" allowfullscreen></iframe>'

    @env.macro
    def image_block(src, alt_text="", caption="", source_text="", source_url="", size="medium", width=None):
        size_map = {"small": "40%", "medium": "60%", "large": "80%"}
        img_width = width if width else size_map.get(size, "60%")
        html = f"""
<figure markdown="span" style="text-align:center;">
    <img src="{src}" alt="{alt_text}" width="{img_width}">
    {f"<figcaption style='font-style:italic; color:#555; margin-top:0.4em;'>{caption}</figcaption>" if caption else ""}
    {f"<p align='right' style='font-size:0.8em'><i>Image Source: <a href='{source_url}' target='_blank'>{source_text}</a></i></p>" if source_url else ""}
</figure>
"""
        return html

    @env.macro
    def youtube_embed(video, title="", width="100%", align="center"):
        """
        Embed a single responsive YouTube video with a 16:9 aspect ratio.
        Accepts both full YouTube URLs and video IDs.
        Width can be customized (e.g., '80%' or '600px').
        """

        import re
        pattern = r"(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})"
        match = re.search(pattern, video)
        video_id = match.group(1) if match else video.strip()

        align_style = "text-align:center;" if align == "center" else f"text-align:{align};"

        html = f"""
<figure style="{align_style} margin:1.5em 0;">
  <div style="position:relative; width:{width}; max-width:100%; padding-bottom:56.25%; height:0; overflow:hidden; border-radius:8px;">
    <iframe
        src="https://www.youtube.com/embed/{video_id}"
        title="{title}"
        frameborder="0"
        style="position:absolute; top:0; left:0; width:100%; height:100%; border:none; border-radius:8px;"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
        allowfullscreen>
    </iframe>
  </div>
  {f"<figcaption style='font-style:italic; color:#555; margin-top:0.5em;'>{title}</figcaption>" if title else ""}
</figure>
"""
        return html
