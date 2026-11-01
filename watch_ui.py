"""Small opaque terminal islands over album artwork; drawing stays on UI thread."""


def lyrics_rect(columns, height, enabled, preferred_width=None):
    if enabled and columns >= 76 and height >= 18:
        width = min(max(24, preferred_width or min(48, max(28, columns // 3))), columns - 48)
        left = columns - width - 3
        return (1, left, width, height - 6)
    return None


def classic_geometry(columns, height, artwork, show_lyrics, preferred_width=None, preferred_info_width=None):
    rect = lyrics_rect(columns, height, show_lyrics, preferred_width)
    cover = None
    if rect:
        available = columns // 3 if columns >= 120 else rect[1] - 5
        info = min(preferred_info_width or 48, available)
        if artwork and columns >= 120 and height >= 18:
            cover = (3, info + 3, rect[1] - info - 6, height - 8)
    elif artwork and columns >= 90 and height >= 18:
        info = min(preferred_info_width or 60, columns // 2)
        cover = (3, info + 3, columns - info - 5, height - 8)
    else:
        info = min(preferred_info_width or max(0, columns - 4), max(0, columns - 4))
    return info, cover, rect


def island(screen, top, left, width, height, label=''):
    import curses
    rows, columns = screen.getmaxyx()
    width, height = min(width, columns - left - 1), min(height, rows - top)
    if width < 3 or height < 2 or top < 0 or left < 0:
        return
    def put(row, col, text, style=0):
        try:
            screen.addnstr(row, col, text, max(0, columns - col - 1), style)
        except curses.error:
            pass
    for row in range(top, top + height):
        put(row, left, ' ' * width)
    put(top, left, '╭' + '─' * (width - 2) + '╮', curses.A_DIM)
    put(top + height - 1, left, '╰' + '─' * (width - 2) + '╯', curses.A_DIM)
    for row in range(top + 1, top + height - 1):
        put(row, left, '│', curses.A_DIM)
        put(row, left + width - 1, '│', curses.A_DIM)
    if label:
        put(top, left + 2, (' ' + label + ' ')[:width - 4], curses.A_BOLD)
