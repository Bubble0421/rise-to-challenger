from api import item_icon_url


def item_icon_html(item_id: int, item_name: str = "", size: int = 32) -> str:
    if not item_id:
        return (
            f"<div style='width:{size}px;height:{size}px;background:#1E2D40;"
            "border-radius:6px;display:inline-block;'></div>"
        )

    safe_name = item_name.replace("'", "&#39;")
    placeholder = (
        f"this.onerror=null;this.outerHTML=`<div style=&quot;width:{size}px;height:{size}px;"
        "background:#1E2D40;border-radius:6px;display:inline-block;&quot;></div>`;"
    )
    return (
        f"<img src='{item_icon_url(item_id)}' alt='{safe_name}' width='{size}' height='{size}' "
        f"style='width:{size}px;height:{size}px;border-radius:6px;object-fit:cover;"
        f"display:inline-block;vertical-align:top;flex-shrink:0;' "
        f"onerror=\"{placeholder}\">"
    )
