from pathlib import Path
import re


# Function to add visual breaks outside code blocks
def add_visual_breaks(md: str) -> str:
    parts = re.split(r"(```.*?```)", md, flags=re.DOTALL)
    for i in range(0, len(parts), 2):  # only transform non-code parts
        parts[i] = parts[i].replace("\\n\\n", "  <br><br>")
    return "".join(parts)


Path("./CLIENT_SIDE_IMPLEMENTATION_ROADMAP.md").write_text(
    add_visual_breaks(Path("./CLIENT_SIDE_IMPLEMENTATION_ROADMAP.md").read_text())
)
