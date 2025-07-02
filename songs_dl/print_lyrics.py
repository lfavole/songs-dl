"""Create a PDF containing the lyrics of the given song."""

import argparse
from pathlib import Path

try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
except ModuleNotFoundError as err:
    msg = "The fpdf2 module was not found. Please reinstall songs-dl with pip install songs-dl[lyrics]."
    raise ModuleNotFoundError(msg) from err
from mutagen.id3._util import ID3NoHeaderError  # noqa: PLC2701

from songs_dl.utils import Song


def print_lyrics(*songs_or_lyrics: str) -> None:
    """Create a PDF with lyrics from one or more songs."""
    song_files = []
    for file in songs_or_lyrics:
        song_files.extend(Path().glob(file))

    songs = []
    for song in song_files:
        try:
            songs.append(Song.from_id3(song))
        except ID3NoHeaderError:  # noqa: PERF203
            songs.append(Path(song).read_text("utf-8"))

    pdf = FPDF()
    pdf.add_font("Montserrat", "", "C:/Windows/Fonts/Montserrat-Regular.ttf")
    pdf.add_font("Montserrat", "B", "C:/Windows/Fonts/Montserrat-Bold.ttf")
    pdf.add_font("Montserrat", "I", "C:/Windows/Fonts/Montserrat-Italic.ttf")
    pdf.set_font("Montserrat")

    for song in songs:
        pdf.add_page()
        if isinstance(song, Song):
            with pdf.local_context(font_style="B", font_size=28):
                pdf.multi_cell(0, text=song.title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            with pdf.local_context(font_style="I", font_size=16):
                pdf.multi_cell(0, text=", ".join(song.artists), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln()

            lyrics = song.lyrics
            if isinstance(lyrics, list):
                lyrics = "\n".join(line[0] for line in lyrics)
        else:
            lyrics = song

        with pdf.text_columns(ncols=2) as cols:
            cols.write(lyrics)
            if isinstance(song, Song) and song.picture and song.picture.pillow:
                cols.ln()
                cols.ln()

                img = song.picture.pillow
                col_width = cols.extents.right - cols.extents.left
                avail_size = pdf.h - pdf.y - pdf.b_margin

                # 1200 px x 900 px
                # wh = 900 / 1200 = 0.75
                # width = 1200 * 0.75 = 900 px
                # height = 900 / 0.75 = 1200 px
                wh = img.width / img.height

                size = {"height": avail_size, "width": avail_size * wh}
                if size["width"] > col_width:
                    size = {"width": col_width, "height": col_width / wh}

                cols.image(img, **size, keep_aspect_ratio=True)

    file = "lyrics.pdf"
    pdf.output(file)


def main() -> None:
    """Run the CLI."""
    parser = argparse.ArgumentParser(fromfile_prefix_chars="@")
    parser.add_argument("SONG_OR_LYRICS", nargs="+", help="songs for which we will print the lyrics or lyrics files")

    args = parser.parse_args()
    print_lyrics(*args.SONG_OR_LYRICS)


if __name__ == "__main__":
    main()
