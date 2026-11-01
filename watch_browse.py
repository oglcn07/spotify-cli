"""Paginated collection browsing, without additional library permissions."""


def collection_page(sp, request):
    item = request['item']
    from watch_pins import clean_pin
    try:
        kind = clean_pin(item)['type']
    except ValueError:
        raise RuntimeError('Bu sonuç bir koleksiyon değil.') from None
    offset = max(0, int(request.get('offset', 0)))
    limit = 10
    if kind == 'album':
        page = sp.album_tracks(item['uri'], limit=limit, offset=offset)
        items = page.get('items') or []
    elif kind == 'artist':
        page = sp.artist_albums(item['uri'], limit=limit, offset=offset)
        items = page.get('items') or []
    elif kind == 'playlist':
        # Spotipy 2.26's public wrapper still targets the deprecated /tracks route.
        playlist_id = item['uri'].split(':')[-1]
        page = sp._get(f'playlists/{playlist_id}/items', limit=limit, offset=offset)
        items = [(entry.get('item') or entry.get('track')) for entry in (page.get('items') or []) if entry]
    else:
        raise RuntimeError('Bu sonuç bir koleksiyon değil.')
    items = [entry for entry in items if entry and entry.get('uri', '').startswith('spotify:')
             and not entry.get('is_local') and entry.get('type', 'track') != 'episode']
    return {**request, 'limit': limit, 'offset': offset, 'next': bool(page.get('next')), 'items': items}


def parse_timestamp(text):
    try:
        parts = text.strip().split(':')
        if len(parts) not in (1, 2) or not all(part.isdigit() for part in parts):
            raise ValueError
        if len(parts) == 2 and int(parts[1]) >= 60:
            raise ValueError
        seconds = int(parts[0]) if len(parts) == 1 else int(parts[0]) * 60 + int(parts[1])
        return seconds
    except (ValueError, AttributeError):
        raise ValueError('Süreyi saniye veya dakika:saniye olarak yaz (örnek: 2:15).') from None


def seek_target(state, delta=0, target=None):
    if not state or not state.get('title'):
        raise RuntimeError('Sarmak için önce bir şarkı çal.')
    seconds = target if target is not None else state.get('position_precise', state.get('position', 0)) + delta
    duration = state.get('mpris:length', 0)
    return round(max(0, min(seconds, duration) if duration else seconds) * 1000)
