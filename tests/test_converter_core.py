import os
import subprocess
import sys
from pathlib import Path

import pytest

import wav2flac.app as converter


@pytest.fixture(autouse=True)
def fake_ffmpeg(monkeypatch):
    monkeypatch.setattr(converter, "which", lambda name: "ffmpeg")


def test_parse_directory_structure_extracts_artist_album_year_and_track(tmp_path):
    source = tmp_path / "Music"
    audio_file = source / "Artist Name" / "Album Name (2023)" / "01 Track Name.wav"
    audio_file.parent.mkdir(parents=True)
    audio_file.write_bytes(b"audio")

    lookup = converter.AdvancedMetadataLookup(enable_fingerprinting=False)

    metadata = lookup.parse_directory_structure(audio_file, source)

    assert metadata["artist"] == "Artist Name"
    assert metadata["album"] == "Album Name"
    assert metadata["year"] == "2023"
    assert metadata["track_number"] == "01"
    assert metadata["title"] == "01 Track Name"
    assert metadata["is_generic"] is False


@pytest.mark.parametrize("filename", ["Track 01", "01 Track", "Pista 02", "05", "audio 7"])
def test_generic_filename_detection(filename):
    lookup = converter.AdvancedMetadataLookup(enable_fingerprinting=False)

    assert lookup._is_generic_filename(filename) is True


def test_relative_output_path_resolves_next_to_source(tmp_path):
    source = tmp_path / "Music"
    source.mkdir()

    app = converter.EnhancedWAVToFLACConverter(str(source), enable_metadata=False, dry_run=True)

    assert app.output_path == tmp_path / "FLAC CONVERTER"


def test_import_does_not_create_log_file(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", "import wav2flac.app"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert not (tmp_path / "conversion_enhanced.log").exists()


def test_configure_logging_creates_parent_directory(tmp_path):
    log_file = tmp_path / "logs" / "conversion.log"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from wav2flac.app import configure_logging, logger; "
                f"configure_logging(r'{log_file}'); "
                "logger.info('hello')"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert log_file.exists()


def test_dependency_check_is_mode_aware(monkeypatch):
    monkeypatch.setattr(converter, "AudioSegment", object())
    monkeypatch.setattr(converter, "FLAC", None)
    monkeypatch.setattr(converter, "musicbrainzngs", None)
    monkeypatch.setattr(converter, "acoustid", None)

    assert (
        converter.get_missing_dependencies(
            enable_metadata=False,
            basic_metadata=False,
            enable_fingerprinting=False,
            dry_run=False,
        )
        == []
    )
    assert converter.get_missing_dependencies(
        enable_metadata=True,
        basic_metadata=True,
        enable_fingerprinting=False,
        dry_run=False,
    ) == ["mutagen"]
    assert converter.get_missing_dependencies(
        enable_metadata=True,
        basic_metadata=False,
        enable_fingerprinting=True,
        dry_run=False,
    ) == ["musicbrainzngs", "mutagen", "pyacoustid"]


def test_cli_version_uses_package_version():
    result = subprocess.run(
        [sys.executable, "-m", "wav2flac.app", "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert converter.__version__ in result.stdout


def test_cli_fingerprinting_requires_acoustid_key(tmp_path):
    source = tmp_path / "Music"
    source.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wav2flac.app",
            str(source),
            "--dry-run",
            "--fingerprinting",
            "--log-file",
            str(tmp_path / "conversion.log"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "ACOUSTID_API_KEY": "", "PYTHONPATH": str(Path.cwd())},
    )

    assert result.returncode == 1
    assert "ACOUSTID_API_KEY" in result.stderr


def test_metadata_lookup_persists_provider_cache(tmp_path):
    cache_file = tmp_path / "metadata-cache.json"
    lookup = converter.AdvancedMetadataLookup(
        enable_fingerprinting=False,
        cache_file=cache_file,
    )
    lookup.cache["track_artist|album|title"] = {"title": "Title"}
    lookup.album_cache["album_artist|album"] = [{"title": "Track"}]
    lookup.fingerprint_cache["fingerprint_song_123"] = None
    lookup.lastfm_cache["lastfm_artist|title|album"] = {"genre": "Rock"}

    lookup.save_persistent_cache()
    reloaded = converter.AdvancedMetadataLookup(
        enable_fingerprinting=False,
        cache_file=cache_file,
    )

    assert reloaded.cache == lookup.cache
    assert reloaded.album_cache == lookup.album_cache
    assert reloaded.fingerprint_cache == lookup.fingerprint_cache
    assert reloaded.lastfm_cache == lookup.lastfm_cache


def test_audio_fingerprint_lookup_reads_track_number_from_nested_recording(tmp_path, monkeypatch):
    audio_file = tmp_path / "song.wav"
    audio_file.write_bytes(b"audio")

    class FakeAcoustID:
        @staticmethod
        def fingerprint_file(_path):
            return 180, "fingerprint"

        @staticmethod
        def lookup(*_args, **_kwargs):
            return {
                "status": "ok",
                "results": [
                    {
                        "score": 0.95,
                        "recordings": [
                            {
                                "id": "recording-1",
                                "title": "Song",
                                "artists": [{"id": "artist-1", "name": "Artist"}],
                                "releases": [
                                    {
                                        "id": "release-1",
                                        "title": "Album",
                                        "date": "2024",
                                        "mediums": [
                                            {
                                                "tracks": [
                                                    {
                                                        "position": "3",
                                                        "recording": {"id": "recording-1"},
                                                    }
                                                ]
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }

    monkeypatch.setattr(converter, "acoustid", FakeAcoustID)
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""))
    lookup = converter.AdvancedMetadataLookup(enable_fingerprinting=True)

    metadata = lookup.audio_fingerprint_lookup(audio_file)

    assert metadata["track_number"] == "3"


def test_find_audio_files_excludes_output_directory_inside_source(tmp_path):
    source = tmp_path / "Music"
    output = source / "Output"
    keep_file = source / "Artist" / "Album" / "01.wav"
    generated_file = output / "Artist" / "Album" / "01.flac"
    keep_file.parent.mkdir(parents=True)
    generated_file.parent.mkdir(parents=True)
    keep_file.write_bytes(b"audio")
    generated_file.write_bytes(b"generated")

    app = converter.EnhancedWAVToFLACConverter(
        str(source),
        output_folder=str(output),
        enable_metadata=False,
        dry_run=True,
    )

    assert app.find_audio_files() == [keep_file.resolve()]


def test_skip_existing_does_not_convert_existing_wav_output(tmp_path, monkeypatch):
    source = tmp_path / "Music"
    output = tmp_path / "Out"
    wav_file = source / "Artist" / "Album" / "01.wav"
    flac_file = output / "Artist" / "Album" / "01.flac"
    wav_file.parent.mkdir(parents=True)
    flac_file.parent.mkdir(parents=True)
    wav_file.write_bytes(b"audio")
    flac_file.write_bytes(b"existing")

    def fail_convert(*_args, **_kwargs):
        pytest.fail("existing output should not be converted")

    monkeypatch.setattr(converter.EnhancedWAVToFLACConverter, "convert_wav_to_flac", fail_convert)

    app = converter.EnhancedWAVToFLACConverter(
        str(source),
        output_folder=str(output),
        enable_metadata=False,
        skip_existing=True,
    )

    assert app.process_single_file(wav_file) is True
    assert app.stats["skipped_existing"] == 1
    assert app.stats["converted"] == 0


def test_existing_wav_output_is_reused_by_default(tmp_path, monkeypatch):
    source = tmp_path / "Music"
    output = tmp_path / "Out"
    wav_file = source / "Artist" / "Album" / "01.wav"
    flac_file = output / "Artist" / "Album" / "01.flac"
    wav_file.parent.mkdir(parents=True)
    flac_file.parent.mkdir(parents=True)
    wav_file.write_bytes(b"audio")
    flac_file.write_bytes(b"existing")

    def fail_convert(*_args, **_kwargs):
        pytest.fail("existing output should be reused without conversion")

    monkeypatch.setattr(converter.EnhancedWAVToFLACConverter, "convert_wav_to_flac", fail_convert)

    app = converter.EnhancedWAVToFLACConverter(
        str(source),
        output_folder=str(output),
        enable_metadata=False,
    )

    assert app.process_single_file(wav_file) is True
    assert app.stats["reused_existing"] == 1
    assert app.stats["converted"] == 0


def test_high_quality_conversion_preserves_source_sample_format(tmp_path, monkeypatch):
    captured = {}

    class FakeAudio:
        def export(self, output_path, **kwargs):
            captured.update(kwargs)
            Path(output_path).write_bytes(b"flac")

    class FakeAudioSegment:
        @staticmethod
        def from_wav(_input_path):
            return FakeAudio()

    monkeypatch.setattr(converter, "AudioSegment", FakeAudioSegment)
    source = tmp_path / "Music"
    source.mkdir()
    input_file = source / "song.wav"
    output_file = tmp_path / "song.flac"
    input_file.write_bytes(b"audio")
    app = converter.EnhancedWAVToFLACConverter(str(source), enable_metadata=False)

    assert app.convert_wav_to_flac(input_file, output_file) is True
    assert captured["parameters"] == ["-compression_level", "12"]


def test_compatibility_conversion_forces_16_bit_sample_format(tmp_path, monkeypatch):
    captured = {}

    class FakeAudio:
        def export(self, output_path, **kwargs):
            captured.update(kwargs)
            Path(output_path).write_bytes(b"flac")

    class FakeAudioSegment:
        @staticmethod
        def from_wav(_input_path):
            return FakeAudio()

    monkeypatch.setattr(converter, "AudioSegment", FakeAudioSegment)
    source = tmp_path / "Music"
    source.mkdir()
    input_file = source / "song.wav"
    output_file = tmp_path / "song.flac"
    input_file.write_bytes(b"audio")
    app = converter.EnhancedWAVToFLACConverter(str(source), enable_metadata=False, compatibility_mode=True)

    assert app.convert_wav_to_flac(input_file, output_file) is True
    assert captured["parameters"] == ["-compression_level", "8", "-sample_fmt", "s16"]


def test_embed_metadata_preserves_unmanaged_existing_tags(monkeypatch):
    fake_file = {"PICTURE": ["cover-art"]}
    calls = {"delete": 0, "save": 0}

    class FakeFLAC:
        def __init__(self, _path):
            self.tags = fake_file

        def __setitem__(self, key, value):
            self.tags[key] = value

        def delete(self):
            calls["delete"] += 1

        def save(self):
            calls["save"] += 1

    monkeypatch.setattr(converter, "FLAC", FakeFLAC)
    app = converter.EnhancedWAVToFLACConverter.__new__(converter.EnhancedWAVToFLACConverter)

    assert app.embed_metadata(Path("song.flac"), {"title": "Song Title", "artist": "Artist"}) is True
    assert fake_file["PICTURE"] == ["cover-art"]
    assert fake_file["TITLE"] == "Song Title"
    assert fake_file["ARTIST"] == "Artist"
    assert calls == {"delete": 0, "save": 1}
