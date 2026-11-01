"""Interactive live API smoke check (not part of the offline test suite)."""

from spotify import get_spotify


def main():
    sp = get_spotify()
    print("Spotify API bağlantısı deneniyor...")
    results = sp.search(q="Demir Demirkan Zaferlerim", type="track", limit=3)
    for track in results["tracks"]["items"]:
        artists = ", ".join(a["name"] for a in track["artists"])
        print(f"{artists} - {track['name']} | {track['uri']}")


if __name__ == "__main__":
    main()
