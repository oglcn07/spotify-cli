"""Background album-cover loading and a small curses pixel-art panel."""

from collections import OrderedDict
import io
import queue
import threading
import urllib.request

from PIL import Image, ImageOps


XTERM_LEVELS = (0, 95, 135, 175, 215, 255)
XTERM_PALETTE = [
    (red, green, blue)
    for red in XTERM_LEVELS for green in XTERM_LEVELS for blue in XTERM_LEVELS
] + [(8 + step * 10,) * 3 for step in range(24)]


def terminal_color(pixel):
    """Use actual xterm RGB values, including its dedicated grayscale ramp."""
    return 16 + min(
        range(len(XTERM_PALETTE)),
        key=lambda i: sum((a - b) ** 2 for a, b in zip(pixel, XTERM_PALETTE[i]))
    )


def cover_url(item):
    decorations = (item or {}).get("decorations") or {}
    parent = (decorations.get("parent") or {}).get("entity") or {}
    for source in (decorations, parent.get("decorations") or {}):
        covers = (source.get("visual_identity") or {}).get("cover") or []
        covers = [cover for cover in covers if cover.get("url", "").startswith("https://")]
        if covers:
            return next((c["url"] for c in covers if c.get("size") == "default"), covers[0]["url"])
    return ""


def download_cover(url):
    with urllib.request.urlopen(url, timeout=4) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Cover too large")
    with Image.open(io.BytesIO(data)) as image:
        if image.width * image.height > 4_000_000:
            raise ValueError("Cover dimensions too large")
        return ImageOps.fit(image.convert("RGB"), (96, 96), method=Image.Resampling.BOX)


class AlbumArt:
    def __init__(self):
        self.jobs = queue.Queue(maxsize=1)
        self.results = queue.Queue()
        self.stopped = threading.Event()
        self.url = None
        self.image = None
        self.message = "Kapak yok"
        self.rendered = None
        self.render_size = None
        self.colors = None
        self.color_mode = None
        self.pairs = set()
        self.thread = threading.Thread(target=self._load, daemon=True)
        self.thread.start()

    def request(self, url):
        if url == self.url:
            return
        self.url, self.image = url, None
        self.rendered, self.render_size = None, None
        self.message = "Kapak yükleniyor..." if url else "Kapak yok"
        # Keep only the latest requested cover when tracks change quickly.
        try:
            self.jobs.get_nowait()
        except queue.Empty:
            pass
        self.jobs.put_nowait(url)

    def _load(self):
        cache = OrderedDict()
        while not self.stopped.is_set():
            url = self.jobs.get()
            if self.stopped.is_set():
                return
            if not url:
                continue
            try:
                if url not in cache:
                    cache[url] = download_cover(url)
                cache.move_to_end(url)
                while len(cache) > 8:
                    cache.popitem(last=False)
                self.results.put((url, cache[url], ""))
            except Exception:
                self.results.put((url, None, "Kapak alınamadı"))

    def poll(self):
        while True:
            try:
                url, image, message = self.results.get_nowait()
            except queue.Empty:
                return
            if url == self.url:
                self.image, self.message = image, message
                self.rendered, self.render_size = None, None

    def draw(self, screen, top, left, width, height, mode="8-bit", background=False, brightness=45):
        import curses

        self.poll()
        if background:
            square = min(width // 2, height)
            if square < 1:
                return
            left += (width - square * 2) // 2
            top += (height - square) // 2
            width, height = square * 2, square
        side = min(40, width // 2, height)
        if (side < 8 and not background) or width < 2 or height < 1:
            return
        if self.colors is None or self.color_mode != mode:
            self.color_mode = mode
            self.pairs.clear()
            self.colors = False
            if mode != "ASCII" and curses.has_colors() and curses.COLORS >= 256 and curses.COLOR_PAIRS > 240:
                try:
                    if mode != "16-bit":
                        for color in range(240):
                            curses.init_pair(color + 1, 16 + color, 16 + color)
                    self.colors = True
                except curses.error:
                    pass
        if not background:
            left += (width - side * 2) // 2
        if self.image is None:
            if background:
                return
            try:
                screen.addnstr(top, left, self.message, side * 2)
            except curses.error:
                pass
            return
        # All modes occupy the same square; 8-bit uses larger, nearest-neighbor pixels.
        detailed = mode in ("16-bit", "Glitch") and self.colors
        rows = height if background else side
        columns = width // (1 if detailed else 2) if background else side * (2 if detailed else 1)
        size = rows * (2 if detailed else 1)
        render_key = (rows, columns, mode, background, brightness)
        if self.render_size != render_key:
            if background:
                # Terminal cells are roughly twice as tall as they are wide.
                canvas = self.image.resize((width, height * 2), Image.Resampling.BOX)
                canvas = canvas.point(lambda channel: int(channel * max(15, min(85, brightness)) / 100))
            else:
                canvas = self.image
            if mode == "8-bit":
                coarse_width = min(40 if background else 16, columns)
                coarse_height = min(24 if background else 16, rows)
                self.rendered = canvas.resize((coarse_width, coarse_height), Image.Resampling.BOX).resize(
                    (columns, rows), Image.Resampling.NEAREST)
            else:
                self.rendered = canvas.resize((columns, size), Image.Resampling.BOX)
            self.pairs.clear()
            if detailed and mode != "Glitch":
                # color_pair() exposes only IDs 0..255, even with extended ncurses.
                # Fifteen adaptive image colors need at most 15 * 15 = 225 pairs.
                self.indexed = self.rendered.quantize(
                    colors=15, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
                )
                palette = self.indexed.getpalette()
                self.palette = [terminal_color(palette[i:i + 3]) for i in range(0, 45, 3)]
            else:
                # Cache the per-pixel terminal conversion until the cover/size changes.
                self.pixel_colors = {
                    pixel: terminal_color(pixel)
                    for pixel in {self.rendered.getpixel((x, y))
                                  for y in range(size) for x in range(columns)}
                } if self.colors and mode not in ("ASCII", "Glitch") else {}
            self.render_size = render_key
        pixels = self.rendered.load()
        indexed = self.indexed.load() if detailed and mode != "Glitch" else None
        ramp = " .:-=+*#%@"
        for row in range(rows):
            for column in range(columns):
                red, green, blue = pixels[column, row * 2 if detailed else row]
                if detailed and mode == "Glitch":
                    # Preserve the original accidental pair-ID aliasing as an effect.
                    levels = 6 if curses.COLOR_PAIRS > 216 * 216 else 2
                    def glitch_color(pixel):
                        parts = [round(value * (levels - 1) / 255) for value in pixel]
                        index = parts[0] * levels * levels + parts[1] * levels + parts[2]
                        scale = 5 // (levels - 1)
                        return index, 16 + parts[0] * scale * 36 + parts[1] * scale * 6 + parts[2] * scale
                    upper, foreground = glitch_color((red, green, blue))
                    lower, background = glitch_color(pixels[column, row * 2 + 1])
                    pair = 1 + upper * levels ** 3 + lower
                    if pair not in self.pairs:
                        curses.init_pair(pair, foreground, background)
                        self.pairs.add(pair)
                    text, style = "▀", curses.color_pair(pair % 256)
                elif detailed:
                    upper = indexed[column, row * 2]
                    lower = indexed[column, row * 2 + 1]
                    pair = 1 + upper * 15 + lower
                    if pair not in self.pairs:
                        curses.init_pair(pair, self.palette[upper], self.palette[lower])
                        self.pairs.add(pair)
                    text, style = "▀", curses.color_pair(pair)
                elif self.colors and mode != "ASCII":
                    color = self.pixel_colors[(red, green, blue)]
                    text, style = "  ", curses.color_pair(color - 15)
                else:
                    brightness = (red * 299 + green * 587 + blue * 114) // 1000
                    text, style = ramp[brightness * (len(ramp) - 1) // 255] * 2, 0
                try:
                    screen.addstr(top + row, left + column * (1 if detailed else 2), text, style)
                except curses.error:
                    pass

    def close(self):
        self.stopped.set()
        try:
            self.jobs.get_nowait()
        except queue.Empty:
            pass
        self.jobs.put_nowait(None)
