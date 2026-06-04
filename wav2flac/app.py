#!/usr/bin/env python3
"""
Enhanced WAV to FLAC Converter with Advanced Metadata Lookup and Audio Fingerprinting

This script converts all WAV files in a given directory to FLAC format
while maintaining the highest quality, preserving the folder structure,
and using advanced metadata lookup strategies including audio fingerprinting
for unknown tracks.

Features:
- Intelligent directory structure parsing (Artist/Album/Track)
- Album-based metadata lookup for generic filenames
- Multi-language artist support with fallback strategies
- Smart track matching by position for generic files
- Audio fingerprinting for unknown tracks (AcoustID)
- Skip conversion for existing FLAC files
- Only lookup metadata if incomplete
- Comprehensive metadata embedding with multiple sources
- Rate limiting and caching for efficient API usage
- Detailed logging and progress tracking

Requirements:
- pydub
- mutagen
- musicbrainzngs
- pyacoustid
- ffmpeg (for pydub to work with FLAC)

Usage:
    python wav_to_flac_converter.py <source_path> [options]
"""

import os
import sys
import argparse
import json
import re
import time
from pathlib import Path
from shutil import which
import logging
from typing import List, Tuple, Dict, Optional
from difflib import SequenceMatcher

try:
    from pydub import AudioSegment
except ImportError:
    AudioSegment = None

try:
    from mutagen.flac import FLAC
except ImportError:
    FLAC = None

try:
    import musicbrainzngs
except ImportError:
    musicbrainzngs = None

try:
    import acoustid
except ImportError:
    acoustid = None

try:
    import pylast
except ImportError:
    pylast = None

# Load environment variables from .env file
try:
    from dotenv import load_dotenv

    load_dotenv()  # This loads the .env file
except ImportError:
    # dotenv not installed, will fall back to system environment variables
    pass

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__version__ = "2.3.0"


def configure_logging(log_file: str = "conversion_enhanced.log"):
    """Configure CLI logging without creating files at import time."""
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if any(getattr(handler, "_wav2flac_handler", False) for handler in logger.handlers):
        return

    log_path = Path(log_file).expanduser()
    if log_path.parent != Path("."):
        log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    stream_handler = logging.StreamHandler()

    for handler in (file_handler, stream_handler):
        handler.setFormatter(formatter)
        handler._wav2flac_handler = True
        logger.addHandler(handler)


# Configure MusicBrainz client
if musicbrainzngs:
    musicbrainzngs.set_useragent(
        "Enhanced-WAV-to-FLAC-Converter", "2.1", "https://github.com/user/wav-to-flac-converter"
    )

# AcoustID API key (free tier)
ACOUSTID_API_KEY = os.getenv("ACOUSTID_API_KEY", "YOUR_ACOUSTID_API_KEY")  # Get from https://acoustid.org/api-key

# Last.fm API configuration
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY", "YOUR_LASTFM_API_KEY")  # Get from https://www.last.fm/api
LASTFM_API_SECRET = os.getenv("LASTFM_API_SECRET", "YOUR_LASTFM_SECRET")  # Optional for read-only operations


def has_acoustid_key() -> bool:
    """Return True when an AcoustID API key is configured."""
    return bool(ACOUSTID_API_KEY.strip()) and ACOUSTID_API_KEY != "YOUR_ACOUSTID_API_KEY"


def get_missing_dependencies(
    *,
    enable_metadata: bool,
    basic_metadata: bool,
    enable_fingerprinting: bool,
    dry_run: bool,
) -> List[str]:
    """Return only dependencies required for the selected run mode."""
    if dry_run:
        return []

    missing = []
    if AudioSegment is None:
        missing.append("pydub")

    if enable_metadata:
        if FLAC is None:
            missing.append("mutagen")
        if not basic_metadata and musicbrainzngs is None:
            missing.append("musicbrainzngs")
        if enable_fingerprinting and acoustid is None:
            missing.append("pyacoustid")

    return sorted(set(missing))


class AdvancedMetadataLookup:
    """Advanced metadata lookup class with intelligent fallback strategies including audio fingerprinting."""

    def __init__(
        self,
        enable_fingerprinting: bool = True,
        aggressive_metadata: bool = False,
        cache_file: Optional[Path] = None,
        use_persistent_cache: bool = True,
    ):
        self.cache = {}
        self.album_cache = {}
        self.fingerprint_cache = {}
        self.lastfm_cache = {}
        self.rate_limit_delay = 1.1  # MusicBrainz requires 1 request per second
        self.last_request_time = 0
        self.enable_fingerprinting = enable_fingerprinting
        self.fingerprint_enabled = enable_fingerprinting
        self.aggressive_metadata = aggressive_metadata
        self.cache_file = Path(cache_file) if cache_file and use_persistent_cache else None

        if self.cache_file:
            self._load_persistent_cache()

        # Initialize Last.fm API if available
        self.lastfm_enabled = False
        try:
            if pylast and LASTFM_API_KEY != "YOUR_LASTFM_API_KEY":
                self.lastfm_network = pylast.LastFMNetwork(api_key=LASTFM_API_KEY, api_secret=LASTFM_API_SECRET)
                self.lastfm_enabled = True
                logger.info("[LASTFM] Last.fm API enabled")
            elif not pylast:
                logger.info("[LASTFM] pylast dependency not installed")
            else:
                logger.info("[LASTFM] Last.fm API key not configured")
        except Exception as e:
            logger.warning(f"[LASTFM] Last.fm API disabled due to error: {e}")
            self.lastfm_enabled = False

        # Test AcoustID availability
        if enable_fingerprinting:
            try:
                if acoustid:
                    logger.info("[ACOUSTID] Audio fingerprinting enabled")
                    self.fingerprint_enabled = True
                else:
                    logger.info("[ACOUSTID] pyacoustid dependency not installed")
                    self.fingerprint_enabled = False
            except Exception as e:
                logger.warning(f"[ACOUSTID] Audio fingerprinting disabled due to error: {e}")
                self.fingerprint_enabled = False

        self.generic_patterns = [
            r"^track\s*\d+",  # "Track 01", "Track01", "track 5"
            r"^\d+[\s\-_\.]*track\d*$",  # "01 Track", "01-Track", "05. Track05"
            r"^\d+[\s\-_\.]*$",  # "01", "02", "05."
            r"^\d+[\s\-_\.]+\d+$",  # "01 01", "05. 05"
            r"^track[\s\-_\.]*\d+",  # "Track.01", "Track-05"
            r"^\d+[\s\-_\.]*(track|titulo|cancion|song)\d*$",  # Multi-language
            r"^(track|titulo|cancion|song)[\s\-_\.]*\d+",  # "Song 01", "Cancion 02"
            r"untitled[\s\-_]*\d*",
            r"^audio[\s\-_]*\d+",  # "Audio 01"
            r"^pista[\s\-_]*\d+",  # Spanish: "Pista 01"
        ]

    def _load_persistent_cache(self):
        """Load cached provider results from disk when available."""
        try:
            if not self.cache_file or not self.cache_file.exists():
                return

            with self.cache_file.open("r", encoding="utf-8") as cache_handle:
                data = json.load(cache_handle)

            self.cache.update(data.get("tracks", {}))
            self.album_cache.update(data.get("albums", {}))
            self.fingerprint_cache.update(data.get("fingerprints", {}))
            self.lastfm_cache.update(data.get("lastfm", {}))
            logger.info(f"[CACHE] Loaded metadata cache: {self.cache_file}")
        except Exception as e:
            logger.warning(f"[CACHE] Could not load metadata cache: {e}")

    def save_persistent_cache(self):
        """Persist provider lookup caches for future runs."""
        if not self.cache_file:
            return

        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "tracks": self.cache,
                "albums": self.album_cache,
                "fingerprints": self.fingerprint_cache,
                "lastfm": self.lastfm_cache,
            }
            with self.cache_file.open("w", encoding="utf-8") as cache_handle:
                json.dump(data, cache_handle, ensure_ascii=False, indent=2, sort_keys=True)
            logger.info(f"[CACHE] Saved metadata cache: {self.cache_file}")
        except Exception as e:
            logger.warning(f"[CACHE] Could not save metadata cache: {e}")

    def _rate_limit(self):
        """Ensure we don't exceed MusicBrainz rate limits."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - time_since_last)
        self.last_request_time = time.time()

    def _is_metadata_complete(self, metadata: Dict[str, str]) -> bool:
        """Check if metadata is complete enough to skip lookup."""
        essential_fields = ["title", "artist", "album"]
        musicbrainz_fields = ["musicbrainz_recordingid", "musicbrainz_trackid"]

        # Check if all essential fields are present and not generic
        for field in essential_fields:
            if not metadata.get(field) or metadata[field].strip() == "":
                return False

        # Check if title appears to be generic
        title = metadata.get("title", "")
        if self._is_generic_filename(title):
            logger.info(f"  [INCOMPLETE] Title '{title}' appears generic")
            return False

        # Check if we already have MusicBrainz IDs
        has_musicbrainz = any(metadata.get(field) for field in musicbrainz_fields)
        if has_musicbrainz:
            logger.info("  [COMPLETE] Metadata has MusicBrainz ID, skipping lookup")
            return True

        # Consider complete if we have good title, artist, and album
        logger.info("  [PARTIAL] Has basic metadata but no MusicBrainz ID")
        return False

    def get_existing_metadata(self, file_path: Path) -> Dict[str, str]:
        """Extract existing metadata from audio file."""
        metadata = {}

        try:
            if file_path.suffix.lower() == ".flac":
                audio_file = FLAC(str(file_path))

                # Map FLAC tags to our metadata format
                tag_mapping = {
                    "TITLE": "title",
                    "ARTIST": "artist",
                    "ALBUM": "album",
                    "DATE": "date",
                    "TRACKNUMBER": "track_number",
                    "GENRE": "genre",
                    "ALBUMARTIST": "albumartist",
                    "COMPOSER": "composer",
                    "MUSICBRAINZ_TRACKID": "musicbrainz_recordingid",
                    "MUSICBRAINZ_ALBUMID": "musicbrainz_albumid",
                    "MUSICBRAINZ_ARTISTID": "musicbrainz_artistid",
                }

                for flac_tag, meta_key in tag_mapping.items():
                    if flac_tag in audio_file:
                        value = (
                            audio_file[flac_tag][0] if isinstance(audio_file[flac_tag], list) else audio_file[flac_tag]
                        )
                        if value and str(value).strip():
                            metadata[meta_key] = str(value).strip()

                logger.info(f"  [EXISTING_META] Found {len(metadata)} metadata fields in FLAC")

        except Exception as e:
            logger.warning(f"  [META_READ_ERROR] Could not read existing metadata: {e}")

        return metadata

    def audio_fingerprint_lookup(self, file_path: Path) -> Optional[Dict[str, str]]:
        """Use audio fingerprinting to identify unknown tracks."""
        if not self.fingerprint_enabled:
            return None

        cache_key = f"fingerprint_{file_path.name}_{file_path.stat().st_size}"
        if cache_key in self.fingerprint_cache:
            return self.fingerprint_cache[cache_key]

        try:
            logger.info(f"  [FINGERPRINT] Analyzing audio fingerprint for: {file_path.name}")

            # Check if fpcalc is available
            try:
                import subprocess

                result = subprocess.run(["fpcalc", "--version"], capture_output=True, text=True, timeout=5)
                # fpcalc returns error code 1 for --version but that's normal, just check if it runs
            except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
                try:
                    # Try without --version
                    result = subprocess.run(["fpcalc"], capture_output=True, text=True, timeout=5)
                    if "No input files" not in result.stderr:
                        logger.warning("  [FINGERPRINT] fpcalc not found or not working properly")
                        self.fingerprint_enabled = False
                        self.fingerprint_cache[cache_key] = None
                        return None
                except Exception as e:
                    logger.warning(f"  [FINGERPRINT] fpcalc not available: {e}")
                    self.fingerprint_enabled = False
                    self.fingerprint_cache[cache_key] = None
                    return None

            # Generate audio fingerprint
            try:
                duration, fingerprint = acoustid.fingerprint_file(str(file_path))
            except Exception as e:
                if "fpcalc" in str(e).lower():
                    logger.warning("  [FINGERPRINT] fpcalc not found in PATH. Please ensure Chromaprint is installed.")
                    logger.info("  [FINGERPRINT] Install guide: https://acoustid.org/chromaprint")
                    self.fingerprint_enabled = False
                else:
                    logger.warning(f"  [FINGERPRINT] Fingerprinting failed: {e}")
                self.fingerprint_cache[cache_key] = None
                return None

            if not fingerprint:
                logger.warning("  [FINGERPRINT] Could not generate fingerprint")
                self.fingerprint_cache[cache_key] = None
                return None

            logger.info(f"  [FINGERPRINT] Generated fingerprint (duration: {duration}s)")

            # Lookup in AcoustID database
            try:
                results = acoustid.lookup(
                    ACOUSTID_API_KEY, fingerprint, duration, meta="recordings releasegroups releases artists"
                )

                if results.get("status") == "ok" and results.get("results"):
                    for result in results["results"]:
                        if result.get("score", 0) > 0.8:  # High confidence threshold
                            recordings = result.get("recordings", [])

                            if recordings:
                                recording = recordings[0]  # Take best match

                                metadata = {
                                    "title": recording.get("title", ""),
                                    "musicbrainz_recordingid": recording.get("id", ""),
                                    "duration": str(duration),
                                    "acoustid_score": str(result.get("score", 0)),
                                }

                                # Get artist info
                                if "artists" in recording:
                                    artists = recording["artists"]
                                    if artists:
                                        metadata["artist"] = artists[0].get("name", "")
                                        metadata["musicbrainz_artistid"] = artists[0].get("id", "")

                                # Get release info
                                if "releases" in recording:
                                    releases = recording["releases"]
                                    if releases:
                                        release = releases[0]
                                        metadata["album"] = release.get("title", "")
                                        metadata["musicbrainz_albumid"] = release.get("id", "")
                                        metadata["date"] = release.get("date", "")

                                        # Get track number from medium
                                        if "mediums" in release:
                                            for medium in release["mediums"]:
                                                if "tracks" in medium:
                                                    for track in medium["tracks"]:
                                                        track_recording = track.get("recording", {})
                                                        if track_recording.get("id") == recording.get("id"):
                                                            metadata["track_number"] = track.get("position", "")
                                                            break

                                logger.info(
                                    f"  [FINGERPRINT_SUCCESS] Identified: {metadata.get('artist', '')} - {metadata.get('title', '')} (Score: {result.get('score', 0):.2f})"
                                )
                                self.fingerprint_cache[cache_key] = metadata
                                return metadata

                logger.info("  [FINGERPRINT] No high-confidence matches found")
                self.fingerprint_cache[cache_key] = None
                return None

            except Exception as e:
                logger.warning(f"  [FINGERPRINT] AcoustID lookup failed: {e}")
                self.fingerprint_cache[cache_key] = None
                return None

        except Exception as e:
            logger.warning(f"  [FINGERPRINT] Fingerprinting failed: {e}")
            self.fingerprint_cache[cache_key] = None
            return None

    def _is_generic_filename(self, filename: str) -> bool:
        """Check if filename appears to be generic (Track 01, etc.)."""
        filename_lower = filename.lower().strip()

        # More comprehensive generic patterns
        generic_patterns = [
            r"^track\s*\d+",  # "Track 01", "Track01", "track 5"
            r"^\d+[\s\-_\.]*track\d*$",  # "01 Track", "01-Track", "05. Track05"
            r"^\d+[\s\-_\.]*$",  # "01", "02", "05."
            r"^\d+[\s\-_\.]+\d+$",  # "01 01", "05. 05"
            r"^track[\s\-_\.]*\d+",  # "Track.01", "Track-05"
            r"^\d+[\s\-_\.]*(track|titulo|cancion|song)\d*$",  # Multi-language
            r"^(track|titulo|cancion|song)[\s\-_\.]*\d+",  # "Song 01", "Cancion 02"
            r"untitled[\s\-_]*\d*",
            r"^audio[\s\-_]*\d+",  # "Audio 01"
            r"^pista[\s\-_]*\d+",  # Spanish: "Pista 01"
        ]

        for pattern in generic_patterns:
            if re.search(pattern, filename_lower):
                logger.info(f"  [GENERIC_DETECTED] '{filename}' matches pattern: {pattern}")
                return True

        logger.info(f"  [NOT_GENERIC] '{filename}' does not match generic patterns")
        return False

    def _extract_track_number(self, filename: str) -> Optional[int]:
        """Extract track number from filename."""
        # Try different patterns
        patterns = [
            r"^(\d+)[\s\-_\.]*",  # Leading number
            r"track[\s\-_]*(\d+)",  # "Track NN"
            r"(\d+)[\s\-_]*track",  # "NN Track"
        ]

        for pattern in patterns:
            match = re.search(pattern, filename.lower())
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
        return None

    def parse_directory_structure(self, file_path: Path, source_path: Path) -> Dict[str, str]:
        """
        Parse directory structure to extract artist, album, and track info.

        Enhanced to handle various structures:
        - Artist/Album/Track.wav
        - Artist - Album/Track.wav
        - Artist/Year - Album/Track.wav
        - Various/Artists - Compilation/Track.wav
        """
        relative_path = file_path.relative_to(source_path)
        parts = relative_path.parts[:-1]  # Exclude filename
        filename = relative_path.stem

        metadata = {
            "title": filename,
            "artist": "",
            "album": "",
            "year": "",
            "track_number": "",
            "is_generic": self._is_generic_filename(filename),
        }

        # Extract track number from filename
        track_num = self._extract_track_number(filename)
        if track_num:
            metadata["track_number"] = str(track_num).zfill(2)

            # For generic filenames, clean up the title
            if metadata["is_generic"]:
                # Remove track number and common prefixes
                clean_title = re.sub(r"^(\d+[\s\-_\.]*)|(track[\s\-_]*\d*[\s\-_]*)", "", filename, flags=re.IGNORECASE)
                metadata["title"] = clean_title.strip() if clean_title.strip() else filename

        if len(parts) >= 1:
            # Last directory is usually the album
            album_part = parts[-1]

            # Check for year in album name (various formats)
            year_patterns = [
                r"\b((?:19|20)\d{2})\b",  # Standard 4-digit year
                r"\(((?:19|20)\d{2})\)",  # Year in parentheses
                r"\[((?:19|20)\d{2})\]",  # Year in brackets
            ]

            for pattern in year_patterns:
                year_match = re.search(pattern, album_part)
                if year_match:
                    metadata["year"] = year_match.group(1)
                    # Remove year from album name
                    album_clean = re.sub(pattern, "", album_part).strip()
                    album_clean = re.sub(r"\s*[-_\(\)\[\]]\s*", " ", album_clean).strip()
                    metadata["album"] = album_clean
                    break
            else:
                metadata["album"] = album_part

        if len(parts) >= 2:
            # Second to last is usually the artist
            artist_part = parts[-2]

            # Handle various artist compilations
            if artist_part.lower() in ["various artists", "various", "compilation", "va"]:
                metadata["artist"] = "Various Artists"
            else:
                metadata["artist"] = artist_part

        # Clean up metadata
        for key in ["title", "artist", "album", "year"]:
            if isinstance(metadata[key], str):
                metadata[key] = metadata[key].strip()

        return metadata

    def search_album_tracks(self, artist: str, album: str) -> Optional[List[Dict[str, str]]]:
        """
        Search for complete album tracklist from MusicBrainz.
        This is useful for matching generic filenames by track position.
        """
        if not all([artist, album]):
            return None

        cache_key = f"album_{artist}|{album}".lower()
        if cache_key in self.album_cache:
            return self.album_cache[cache_key]

        try:
            self._rate_limit()
            logger.info(f"  [ALBUM_SEARCH] Searching for album: {artist} - {album}")

            # Search for releases
            query = f'artist:"{artist}" AND release:"{album}"'

            result = musicbrainzngs.search_releases(query=query, limit=10, strict=False)

            if not result.get("release-list"):
                # Try with partial matching
                query = f"artist:{artist} AND release:{album}"
                result = musicbrainzngs.search_releases(query=query, limit=10, strict=False)

            if result.get("release-list"):
                # Find best matching release
                best_release = None
                best_score = 0

                for release in result["release-list"]:
                    # Calculate similarity score
                    album_score = SequenceMatcher(None, album.lower(), release.get("title", "").lower()).ratio()
                    artist_score = 0

                    if "artist-credit" in release:
                        release_artist = release["artist-credit"][0].get("name", "")
                        artist_score = SequenceMatcher(None, artist.lower(), release_artist.lower()).ratio()

                    total_score = (album_score + artist_score) / 2

                    if total_score > best_score:
                        best_score = total_score
                        best_release = release

                if best_release and best_score > 0.7:  # Minimum similarity threshold
                    release_id = best_release["id"]

                    # Get detailed release info with tracks
                    self._rate_limit()
                    detailed_release = musicbrainzngs.get_release_by_id(
                        release_id, includes=["recordings", "artist-credits", "media"]
                    )

                    if "release" in detailed_release:
                        tracks = []
                        rel = detailed_release["release"]

                        if "medium-list" in rel:
                            for medium in rel["medium-list"]:
                                if "track-list" in medium:
                                    for track in medium["track-list"]:
                                        track_info = {
                                            "position": track.get("position", ""),
                                            "title": (
                                                track["recording"].get("title", "")
                                                if "recording" in track
                                                else track.get("title", "")
                                            ),
                                            "length": track.get("length", ""),
                                            "artist": artist,
                                            "album": best_release.get("title", album),
                                            "date": best_release.get("date", ""),
                                            "musicbrainz_albumid": release_id,
                                        }

                                        if "recording" in track:
                                            track_info["musicbrainz_recordingid"] = track["recording"].get("id", "")

                                        tracks.append(track_info)

                        self.album_cache[cache_key] = tracks
                        logger.info(f"  [ALBUM_FOUND] Found {len(tracks)} tracks for album: {album}")
                        return tracks

            logger.info(f"  [ALBUM_NOT_FOUND] No suitable album found for: {artist} - {album}")
            self.album_cache[cache_key] = None
            return None

        except Exception as e:
            logger.warning(f"  [ALBUM_ERROR] Error searching for album {artist} - {album}: {str(e)}")
            self.album_cache[cache_key] = None
            return None

    def search_track_by_position(self, artist: str, album: str, track_number: int) -> Optional[Dict[str, str]]:
        """Find track metadata by position in album."""
        tracks = self.search_album_tracks(artist, album)
        if not tracks:
            return None

        # Find track by position
        for track in tracks:
            try:
                if int(track.get("position", 0)) == track_number:
                    logger.info(f"  [POSITION_MATCH] Found track {track_number}: {track.get('title')}")
                    return track
            except ValueError:
                continue

        # If exact position not found, try by index (some albums start from 0)
        try:
            if 0 <= track_number - 1 < len(tracks):
                track = tracks[track_number - 1]
                logger.info(f"  [INDEX_MATCH] Found track by index {track_number}: {track.get('title')}")
                return track
        except IndexError:
            pass

        return None

    def search_musicbrainz_individual(self, artist: str, album: str, title: str) -> Optional[Dict[str, str]]:
        """
        Search MusicBrainz for individual track metadata.
        Enhanced with multiple search strategies.
        """
        if not all([artist, title]):
            return None

        cache_key = f"track_{artist}|{album}|{title}".lower()
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            self._rate_limit()
            logger.info(f"  [TRACK_SEARCH] Searching MusicBrainz for: {artist} - {title}")

            # Multiple search strategies
            search_strategies = [
                # Exact match with quotes
                f'artist:"{artist}" AND recording:"{title}"' + (f' AND release:"{album}"' if album else ""),
                # Partial match without quotes
                f"artist:{artist} AND recording:{title}" + (f" AND release:{album}" if album else ""),
                # Fuzzy search with just artist and title
                f"artist:{artist} AND recording:{title}",
                # Very loose search
                f"{artist} {title}",
            ]

            if self.aggressive_metadata:
                search_strategies.extend(
                    [
                        f'recording:"{title}"' + (f' AND release:"{album}"' if album else ""),
                        f"{title} {album}" if album else title,
                    ]
                )

            for i, query in enumerate(search_strategies):
                try:
                    result = musicbrainzngs.search_recordings(query=query, limit=10, strict=False)

                    if result.get("recording-list"):
                        # Find best match
                        best_recording = None
                        best_score = 0

                        for recording in result["recording-list"]:
                            # Calculate similarity scores
                            title_score = SequenceMatcher(
                                None, title.lower(), recording.get("title", "").lower()
                            ).ratio()

                            artist_score = 0
                            if "artist-credit" in recording:
                                rec_artist = recording["artist-credit"][0].get("name", "")
                                artist_score = SequenceMatcher(None, artist.lower(), rec_artist.lower()).ratio()

                            album_score = 0
                            if album and "release-list" in recording:
                                for release in recording["release-list"]:
                                    rel_title = release.get("title", "")
                                    score = SequenceMatcher(None, album.lower(), rel_title.lower()).ratio()
                                    album_score = max(album_score, score)

                            # Weighted average
                            total_score = title_score * 0.5 + artist_score * 0.3 + album_score * 0.2

                            if total_score > best_score:
                                best_score = total_score
                                best_recording = recording

                        # Use result if similarity is high enough
                        min_threshold = 0.8 if i == 0 else 0.6  # Higher threshold for exact searches
                        if best_recording and best_score >= min_threshold:
                            metadata = self._extract_recording_metadata(best_recording, artist, album, title)
                            self.cache[cache_key] = metadata
                            logger.info(f"  [TRACK_FOUND] Found with strategy {i+1}, score: {best_score:.2f}")
                            return metadata

                    if i < len(search_strategies) - 1:
                        self._rate_limit()

                except Exception as e:
                    logger.warning(f"  [SEARCH_ERROR] Strategy {i+1} failed: {str(e)}")
                    continue

            logger.info(f"  [TRACK_NOT_FOUND] No suitable match found for: {artist} - {title}")
            self.cache[cache_key] = None
            return None

        except Exception as e:
            logger.warning(f"  [TRACK_ERROR] Error searching for track {artist} - {title}: {str(e)}")
            self.cache[cache_key] = None
            return None

    def _extract_recording_metadata(
        self, recording: Dict, fallback_artist: str, fallback_album: str, fallback_title: str
    ) -> Dict[str, str]:
        """Extract metadata from MusicBrainz recording object."""
        metadata = {
            "musicbrainz_recordingid": recording.get("id", ""),
            "title": recording.get("title", fallback_title),
            "artist": fallback_artist,
            "album": fallback_album,
        }

        # Get artist info
        if "artist-credit" in recording:
            artist_credit = recording["artist-credit"][0]
            if "artist" in artist_credit:
                metadata["musicbrainz_artistid"] = artist_credit["artist"].get("id", "")
                metadata["artist"] = artist_credit["artist"].get("name", fallback_artist)

        # Get release info
        if "release-list" in recording:
            release = recording["release-list"][0]
            metadata.update(
                {
                    "musicbrainz_albumid": release.get("id", ""),
                    "album": release.get("title", fallback_album),
                    "date": release.get("date", ""),
                }
            )

        return metadata

    def get_metadata(
        self,
        artist: str,
        album: str,
        title: str,
        track_number: Optional[int] = None,
        is_generic: bool = False,
        file_path: Optional[Path] = None,
        existing_metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """
        Main method to get metadata using intelligent fallback strategies.

        Strategy for GENERIC files (pure audio-based search):
        1. Check if existing metadata is complete
        2. Try audio fingerprinting FIRST to get real song title
        3. If fingerprinting succeeds, use real title for Last.fm search
        4. Try album-based lookup as backup
        5. Fall back to directory structure metadata (NO external search with generic names)

        Strategy for NON-GENERIC files:
        1. Check if existing metadata is complete
        2. Try individual track search
        3. Try audio fingerprinting if available
        4. Try Last.fm with known title
        5. Fall back to directory structure metadata
        """
        logger.info(
            f"[METADATA] Processing: {artist} - {album} - {title} (Track: {track_number}, Generic: {is_generic})"
        )

        # Strategy 1: Check if existing metadata is already complete
        if existing_metadata and self._is_metadata_complete(existing_metadata):
            logger.info("  [EXISTING] Metadata is complete, skipping lookup")
            return existing_metadata

        # Strategy 2: For GENERIC files - Audio fingerprinting FIRST (pure audio search)
        if is_generic and file_path and self.fingerprint_enabled:
            logger.info("  [STRATEGY] GENERIC FILE: Attempting pure audio fingerprinting for complete metadata")
            fingerprint_metadata = self.audio_fingerprint_lookup(file_path)
            if fingerprint_metadata:
                logger.info(
                    f"  [FINGERPRINT_SUCCESS] Found complete metadata via audio: {fingerprint_metadata.get('artist', '')} - {fingerprint_metadata.get('title', '')}"
                )

                # Add track number from directory if missing
                if track_number and not fingerprint_metadata.get("track_number"):
                    fingerprint_metadata["track_number"] = str(track_number).zfill(2)

                # Audio fingerprint provides complete, accurate metadata - no need for additional searches!
                logger.info("  [COMPLETE] Using pure audio fingerprint metadata (no external searches needed)")
                return fingerprint_metadata
            else:
                logger.info("  [FINGERPRINT_FAILED] No audio fingerprint match found")

        # Strategy 3: For GENERIC files - Album-based lookup (backup for when fingerprinting fails)
        if is_generic and track_number and artist and album:
            logger.info("  [STRATEGY] GENERIC FILE: Attempting album-based lookup as backup")
            album_metadata = self.search_track_by_position(artist, album, track_number)
            if album_metadata:
                logger.info(f"  [ALBUM_SUCCESS] Found metadata: {album_metadata.get('title', 'Unknown')}")
                return album_metadata
            else:
                logger.info(f"  [ALBUM_FAILED] No track found at position {track_number}")

        # Strategy 4: For NON-GENERIC files - Individual track search
        if not is_generic:
            logger.info("  [STRATEGY] NON-GENERIC FILE: Attempting individual track search")
            track_metadata = self.search_musicbrainz_individual(artist, album, title)
            if track_metadata:
                logger.info("  [TRACK_SUCCESS] Found individual track metadata")
                return track_metadata

            # Try audio fingerprinting for non-generic files too
            if file_path and self.fingerprint_enabled:
                logger.info("  [STRATEGY] NON-GENERIC FILE: Attempting audio fingerprinting")
                fingerprint_metadata = self.audio_fingerprint_lookup(file_path)
                if fingerprint_metadata:
                    logger.info("  [FINGERPRINT_SUCCESS] Found metadata via audio fingerprinting")
                    if track_number and not fingerprint_metadata.get("track_number"):
                        fingerprint_metadata["track_number"] = str(track_number).zfill(2)
                    return fingerprint_metadata

            # Try Last.fm with the known (non-generic) title
            if self.lastfm_enabled:
                logger.info("  [STRATEGY] NON-GENERIC FILE: Attempting Last.fm search with known title")
                lastfm_metadata = self.lastfm_search(artist, title, album)
                if lastfm_metadata:
                    logger.info("  [LASTFM_SUCCESS] Found metadata via Last.fm search")
                    if track_number and not lastfm_metadata.get("track_number"):
                        lastfm_metadata["track_number"] = str(track_number).zfill(2)
                    return lastfm_metadata

        # Strategy 5: For GENERIC files - DO NOT search Last.fm with generic names
        if is_generic:
            logger.info(f"  [STRATEGY] GENERIC FILE: Skipping Last.fm search with generic filename '{title}'")
            logger.info("  [REASON] Searching Last.fm for 'Track01' etc. produces unreliable results")

        # Strategy 6: Fallback to directory structure
        logger.info("  [STRATEGY] Using directory structure metadata as fallback")
        fallback_metadata = {
            "title": title,
            "artist": artist,
            "album": album,
            "track_number": str(track_number).zfill(2) if track_number else "",
        }

        # Merge with any existing metadata
        if existing_metadata:
            for key, value in existing_metadata.items():
                if value and not fallback_metadata.get(key):
                    fallback_metadata[key] = value

        logger.info(
            f"  [FALLBACK] Using metadata: title={fallback_metadata.get('title')}, artist={fallback_metadata.get('artist')}, album={fallback_metadata.get('album')}"
        )
        return fallback_metadata

    def lastfm_search(self, artist: str, title: str, album: str = "") -> Optional[Dict[str, str]]:
        """Search Last.fm for track metadata using text-based search."""
        if not self.lastfm_enabled or not all([artist, title]):
            return None

        cache_key = f"lastfm_{artist}|{title}|{album}".lower()
        if cache_key in self.lastfm_cache:
            return self.lastfm_cache[cache_key]

        try:
            logger.info(f"  [LASTFM] Searching Last.fm for: {artist} - {title}")

            # Add rate limiting for Last.fm API
            time.sleep(0.3)  # Small delay to respect API limits

            # Search for track
            try:
                track = self.lastfm_network.get_track(artist, title)

                # Get track info - fix the method call
                try:
                    # Try to get track info first
                    track_title = track.get_name()
                    track_artist = track.get_artist().get_name() if track.get_artist() else artist
                    track_url = track.get_url()

                    metadata = {
                        "title": track_title or title,
                        "artist": track_artist or artist,
                        "lastfm_url": track_url or "",
                    }

                    # Try to get additional info
                    try:
                        playcount = track.get_playcount()
                        metadata["playcount"] = str(playcount) if playcount else "0"
                    except Exception:
                        metadata["playcount"] = "0"

                    try:
                        listeners = track.get_listener_count()
                        metadata["listeners"] = str(listeners) if listeners else "0"
                    except Exception:
                        metadata["listeners"] = "0"

                    # Get album info if available
                    try:
                        track_album = track.get_album()
                        if track_album:
                            album_title = track_album.get_name()
                            if album_title:
                                metadata["album"] = album_title
                                metadata["lastfm_album_url"] = track_album.get_url() or ""
                        elif album:
                            metadata["album"] = album
                    except Exception:
                        if album:
                            metadata["album"] = album

                    # Get tags/genres
                    try:
                        # Add small delay before tags request to avoid rate limiting
                        time.sleep(0.2)
                        tags = track.get_top_tags(limit=3)
                        if tags:
                            genre_list = [tag.item.get_name() for tag in tags]
                            if genre_list:
                                metadata["genre"] = ", ".join(genre_list)
                                logger.info(f"  [LASTFM] Found genres: {metadata['genre']}")
                    except pylast.WSError as e:
                        if "400" in str(e):
                            logger.info("  [LASTFM] No tags available for this track")
                        else:
                            logger.warning(f"  [LASTFM] Tags lookup failed: {e}")
                    except Exception as e:
                        logger.warning(f"  [LASTFM] Tags lookup error: {e}")

                    # Calculate confidence score based on match quality
                    title_similarity = SequenceMatcher(None, title.lower(), metadata["title"].lower()).ratio()
                    artist_similarity = SequenceMatcher(None, artist.lower(), metadata["artist"].lower()).ratio()
                    confidence = (title_similarity + artist_similarity) / 2
                    metadata["lastfm_confidence"] = str(confidence)

                    if confidence > 0.8:
                        logger.info(
                            f"  [LASTFM_SUCCESS] Found: {metadata['artist']} - {metadata['title']} (Confidence: {confidence:.2f})"
                        )
                        self.lastfm_cache[cache_key] = metadata
                        return metadata
                    else:
                        logger.info(f"  [LASTFM] Low confidence match (Score: {confidence:.2f})")

                except Exception as e:
                    logger.warning(f"  [LASTFM] Error getting track details: {e}")

            except pylast.WSError as e:
                logger.info(f"  [LASTFM] Track not found: {artist} - {title} ({e})")
            except Exception as e:
                logger.warning(f"  [LASTFM] Search error: {e}")

            # Try artist correction if direct search failed
            try:
                artist_obj = self.lastfm_network.get_artist(artist)
                corrected_artist = artist_obj.get_correction()
                if corrected_artist and corrected_artist != artist:
                    logger.info(f"  [LASTFM] Trying corrected artist: {corrected_artist}")
                    track = self.lastfm_network.get_track(corrected_artist, title)

                    track_title = track.get_name()
                    track_artist = track.get_artist().get_name() if track.get_artist() else corrected_artist

                    metadata = {
                        "title": track_title or title,
                        "artist": track_artist or corrected_artist,
                        "album": album,
                        "lastfm_corrected": "true",
                    }

                    logger.info(f"  [LASTFM_CORRECTION] Found with corrected artist: {corrected_artist}")
                    self.lastfm_cache[cache_key] = metadata
                    return metadata

            except Exception:
                pass

            logger.info("  [LASTFM] No suitable matches found")
            self.lastfm_cache[cache_key] = None
            return None

        except Exception as e:
            logger.warning(f"  [LASTFM] Last.fm lookup failed: {e}")
            self.lastfm_cache[cache_key] = None
            return None


class EnhancedWAVToFLACConverter:
    """Enhanced WAV to FLAC converter with advanced metadata handling."""

    def __init__(
        self,
        source_path: str,
        output_folder: str = "FLAC CONVERTER",
        compatibility_mode: bool = False,
        enable_metadata: bool = True,
        aggressive_metadata: bool = False,
        enable_fingerprinting: bool = True,
        basic_metadata: bool = False,
        overwrite: bool = False,
        skip_existing: bool = False,
        dry_run: bool = False,
        cache_file: Optional[str] = None,
        use_persistent_cache: bool = True,
    ):
        self.source_path = Path(source_path).expanduser().resolve()
        self.output_folder = output_folder
        output_path = Path(output_folder).expanduser()
        self.output_path = (
            output_path.resolve() if output_path.is_absolute() else (self.source_path.parent / output_path).resolve()
        )
        self.compatibility_mode = compatibility_mode
        self.enable_metadata = enable_metadata
        self.aggressive_metadata = aggressive_metadata
        self.enable_fingerprinting = enable_fingerprinting
        self.basic_metadata = basic_metadata
        self.overwrite = overwrite
        self.skip_existing = skip_existing
        self.dry_run = dry_run
        self.cache_file = (
            Path(cache_file).expanduser().resolve()
            if cache_file
            else (self.output_path / ".metadata_cache.json").resolve()
        )
        self.use_persistent_cache = use_persistent_cache

        # Verify source path exists
        if not self.source_path.exists():
            raise FileNotFoundError(f"Source path does not exist: {source_path}")
        if not self.source_path.is_dir():
            raise NotADirectoryError(f"Source path must be a directory: {source_path}")

        if self.output_path == self.source_path:
            raise ValueError("Output path must be different from the source path.")

        if self.skip_existing and self.overwrite:
            raise ValueError("--skip-existing and --overwrite cannot be used together.")

        # Check if ffmpeg is available
        if not self.dry_run and not which("ffmpeg"):
            raise RuntimeError("ffmpeg not found. Please install ffmpeg and ensure it's in your PATH.")

        # Initialize metadata lookup
        self.metadata_lookup = (
            AdvancedMetadataLookup(
                enable_fingerprinting=enable_fingerprinting,
                aggressive_metadata=aggressive_metadata,
                cache_file=self.cache_file,
                use_persistent_cache=use_persistent_cache and not basic_metadata,
            )
            if enable_metadata and not dry_run
            else None
        )

        # Statistics
        self.stats = {
            "total_files": 0,
            "converted": 0,
            "failed": 0,
            "skipped_flac": 0,
            "skipped_existing": 0,
            "reused_existing": 0,
            "dry_run_actions": 0,
            "metadata_found": 0,
            "metadata_fallback": 0,
            "metadata_fingerprint": 0,
            "metadata_lastfm": 0,
            "metadata_complete": 0,
            "start_time": time.time(),
        }

        logger.info("Enhanced WAV to FLAC Converter initialized")
        logger.info(f"Source: {self.source_path}")
        logger.info(f"Output: {self.output_path}")
        logger.info(f"Compatibility mode: {self.compatibility_mode}")
        logger.info(f"Metadata enabled: {self.enable_metadata}")
        logger.info(f"Aggressive metadata: {self.aggressive_metadata}")
        logger.info(f"Basic metadata only: {self.basic_metadata}")
        logger.info(f"Audio fingerprinting: {self.enable_fingerprinting}")
        logger.info(f"Overwrite existing output: {self.overwrite}")
        logger.info(f"Skip existing output: {self.skip_existing}")
        logger.info(f"Dry run: {self.dry_run}")
        logger.info(f"Persistent metadata cache: {self.cache_file if self.use_persistent_cache else 'disabled'}")

    def find_audio_files(self) -> List[Path]:
        """Find all WAV and FLAC files in the source directory."""
        audio_files = []
        for root, dirs, files in os.walk(self.source_path):
            root_path = Path(root).resolve()
            dirs[:] = [
                directory
                for directory in dirs
                if not self._is_relative_to((root_path / directory).resolve(), self.output_path)
            ]

            for file in files:
                if file.lower().endswith((".wav", ".flac")):
                    audio_files.append(root_path / file)

        wav_count = sum(1 for f in audio_files if f.suffix.lower() == ".wav")
        flac_count = sum(1 for f in audio_files if f.suffix.lower() == ".flac")
        logger.info(f"Found {len(audio_files)} audio files ({wav_count} WAV, {flac_count} FLAC)")
        return audio_files

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        """Return True when path is equal to or nested below parent."""
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    def get_relative_path(self, file_path: Path) -> Path:
        """Get the relative path from source to maintain folder structure."""
        return file_path.relative_to(self.source_path)

    def create_output_directory(self, relative_path: Path) -> Path:
        """Create the output directory structure."""
        output_dir = self.output_path / relative_path.parent
        if not self.dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def embed_metadata(self, flac_file: Path, metadata: Dict[str, str]) -> bool:
        """Embed metadata into FLAC file using mutagen."""
        try:
            audio_file = FLAC(flac_file)

            # Standard tags
            tag_mapping = {
                "title": "TITLE",
                "artist": "ARTIST",
                "album": "ALBUM",
                "date": "DATE",
                "year": "DATE",
                "track_number": "TRACKNUMBER",
                "genre": "GENRE",
                "albumartist": "ALBUMARTIST",
                "composer": "COMPOSER",
                "comment": "COMMENT",
            }

            # MusicBrainz tags
            mb_mapping = {
                "musicbrainz_recordingid": "MUSICBRAINZ_TRACKID",
                "musicbrainz_albumid": "MUSICBRAINZ_ALBUMID",
                "musicbrainz_artistid": "MUSICBRAINZ_ARTISTID",
                "musicbrainz_releasegroupid": "MUSICBRAINZ_RELEASEGROUPID",
            }

            # Add standard metadata
            for key, flac_key in tag_mapping.items():
                if key in metadata and metadata[key]:
                    audio_file[flac_key] = str(metadata[key])

            # Add MusicBrainz metadata
            for key, flac_key in mb_mapping.items():
                if key in metadata and metadata[key]:
                    audio_file[flac_key] = str(metadata[key])

            # Save metadata
            audio_file.save()

            # Log embedded metadata
            embedded_tags = []
            for key, value in metadata.items():
                if value:
                    embedded_tags.append(f"{key}={value}")

            if embedded_tags:
                logger.info(
                    f"  [METADATA] Embedded: {', '.join(embedded_tags[:3])}{'...' if len(embedded_tags) > 3 else ''}"
                )

            return True

        except Exception as e:
            logger.error(f"  [METADATA_ERROR] Failed to embed metadata: {str(e)}")
            return False

    def convert_wav_to_flac(self, input_file: Path, output_file: Path) -> bool:
        """Convert a single WAV file to FLAC."""
        try:
            # Load the WAV file
            audio = AudioSegment.from_wav(str(input_file))

            # Set export parameters based on mode
            if self.compatibility_mode:
                # Compatibility mode: 16-bit, compression level 8
                export_params = {"format": "flac", "parameters": ["-compression_level", "8", "-sample_fmt", "s16"]}
                logger.info("  [CONVERT] Converting in compatibility mode (16-bit, level 8)")
            else:
                # High quality mode: preserve source sample format, compression level 12
                export_params = {"format": "flac", "parameters": ["-compression_level", "12"]}
                logger.info("  [CONVERT] Converting in high quality mode (preserve source format, level 12)")

            # Export to FLAC
            audio.export(str(output_file), **export_params)

            # Verify the output file was created and has content
            if output_file.exists() and output_file.stat().st_size > 0:
                # Calculate compression ratio
                input_size = input_file.stat().st_size
                output_size = output_file.stat().st_size
                compression_ratio = (1 - output_size / input_size) * 100

                logger.info(f"  [SUCCESS] Converted successfully (Compression: {compression_ratio:.1f}%)")
                return True
            else:
                logger.error("  [ERROR] Output file was not created or is empty")
                return False

        except Exception as e:
            logger.error(f"  [ERROR] Conversion failed: {str(e)}")
            return False

    def process_single_file(self, audio_file: Path) -> bool:
        """Process a single audio file with conversion and metadata."""
        try:
            relative_path = self.get_relative_path(audio_file)
            output_dir = self.create_output_directory(relative_path)

            # Determine output file path
            if audio_file.suffix.lower() == ".wav":
                output_file = output_dir / (audio_file.stem + ".flac")
                needs_conversion = True
            else:  # Already FLAC
                output_file = output_dir / audio_file.name
                needs_conversion = False
                logger.info(f"[PROCESSING] {relative_path} (FLAC - metadata only)")

            output_exists = output_file.exists()

            if self.dry_run:
                if output_exists and self.skip_existing:
                    logger.info(f"[DRY_RUN] Would skip existing output: {output_file}")
                elif needs_conversion:
                    action = "overwrite" if output_exists and self.overwrite else "convert"
                    logger.info(f"[DRY_RUN] Would {action}: {relative_path} -> {output_file}")
                else:
                    action = "copy over" if output_exists and self.overwrite else "copy/process"
                    logger.info(f"[DRY_RUN] Would {action}: {relative_path} -> {output_file}")
                self.stats["dry_run_actions"] += 1
                return True

            if output_exists and self.skip_existing:
                logger.info(f"  [SKIP] Output already exists: {output_file}")
                self.stats["skipped_existing"] += 1
                return True

            if needs_conversion:
                logger.info(f"[PROCESSING] {relative_path}")
                if output_exists and not self.overwrite:
                    logger.info(f"  [REUSE] Output exists, reusing for metadata: {output_file}")
                    self.stats["reused_existing"] += 1
                else:
                    if output_exists:
                        logger.info(f"  [OVERWRITE] Replacing existing output: {output_file}")
                    if not self.convert_wav_to_flac(audio_file, output_file):
                        return False
                    self.stats["converted"] += 1
            else:
                import shutil

                if output_exists and self.overwrite:
                    shutil.copy2(audio_file, output_file)
                    logger.info("  [OVERWRITE] Replaced existing FLAC file")
                elif output_exists:
                    logger.info(f"  [REUSE] Output exists, reusing for metadata: {output_file}")
                    self.stats["reused_existing"] += 1
                else:
                    shutil.copy2(audio_file, output_file)
                    logger.info("  [COPY] Copied existing FLAC file")

                self.stats["skipped_flac"] += 1

            # Handle metadata if enabled
            if self.enable_metadata and self.metadata_lookup:
                # Get existing metadata from the output FLAC file
                existing_metadata = self.metadata_lookup.get_existing_metadata(output_file)

                # Parse directory structure
                dir_metadata = self.metadata_lookup.parse_directory_structure(audio_file, self.source_path)

                # Check if we need to do metadata lookup
                track_number = int(dir_metadata["track_number"]) if dir_metadata["track_number"].isdigit() else None

                if self.basic_metadata:
                    metadata = {
                        "title": dir_metadata["title"],
                        "artist": dir_metadata["artist"],
                        "album": dir_metadata["album"],
                        "track_number": dir_metadata["track_number"],
                    }
                    logger.info("  [BASIC_METADATA] Using directory structure metadata only")
                else:
                    # Get enhanced metadata with all strategies
                    metadata = self.metadata_lookup.get_metadata(
                        artist=dir_metadata["artist"],
                        album=dir_metadata["album"],
                        title=dir_metadata["title"],
                        track_number=track_number,
                        is_generic=dir_metadata.get("is_generic", False),
                        file_path=audio_file,  # Use original file for fingerprinting
                        existing_metadata=existing_metadata,
                    )

                # Add any additional directory metadata
                if dir_metadata.get("year"):
                    metadata["year"] = dir_metadata["year"]
                if dir_metadata.get("track_number"):
                    metadata["track_number"] = dir_metadata["track_number"]

                # Update statistics based on metadata source
                if metadata == existing_metadata:
                    self.stats["metadata_complete"] += 1
                elif metadata.get("acoustid_score"):
                    self.stats["metadata_fingerprint"] += 1
                elif metadata.get("lastfm_confidence"):
                    self.stats["metadata_lastfm"] += 1
                elif metadata.get("musicbrainz_recordingid"):
                    self.stats["metadata_found"] += 1
                else:
                    self.stats["metadata_fallback"] += 1

                # Embed metadata (only if it's different from existing or we have improvements)
                should_update_metadata = (
                    not existing_metadata  # No existing metadata
                    or metadata != existing_metadata  # Different metadata
                    or (
                        not existing_metadata.get("musicbrainz_recordingid") and metadata.get("musicbrainz_recordingid")
                    )  # Adding MusicBrainz ID
                )

                if should_update_metadata:
                    self.embed_metadata(output_file, metadata)
                else:
                    logger.info("  [METADATA] No updates needed - metadata already complete")

            return True

        except Exception as e:
            logger.error(f"[ERROR] Failed to process {audio_file}: {str(e)}")
            return False

    def convert_all(self) -> Tuple[int, int]:
        """Convert all WAV files in the source directory."""
        audio_files = self.find_audio_files()
        self.stats["total_files"] = len(audio_files)

        if not audio_files:
            logger.warning("No audio files found in the source directory")
            return 0, 0

        logger.info(f"Starting conversion of {len(audio_files)} files...")
        logger.info("=" * 80)

        for i, audio_file in enumerate(audio_files, 1):
            logger.info(f"\n[{i}/{len(audio_files)}] Processing file {i} of {len(audio_files)}")

            if not self.process_single_file(audio_file):
                self.stats["failed"] += 1

            # Progress update every 10 files
            if i % 10 == 0:
                elapsed = time.time() - self.stats["start_time"]
                avg_time = elapsed / i
                remaining = (len(audio_files) - i) * avg_time
                logger.info(f"\n[PROGRESS] {i}/{len(audio_files)} files processed. ETA: {remaining/60:.1f} minutes")

        if self.metadata_lookup:
            self.metadata_lookup.save_persistent_cache()

        return self.stats["converted"], self.stats["failed"]

    def print_summary(self):
        """Print conversion summary."""
        elapsed = time.time() - self.stats["start_time"]

        print("\n" + "=" * 80)
        print("CONVERSION SUMMARY")
        print("=" * 80)
        print(f"Total files found:      {self.stats['total_files']}")
        print(f"WAV files converted:    {self.stats['converted']}")
        print(f"FLAC files processed:   {self.stats['skipped_flac']}")
        print(f"Existing files reused:  {self.stats['reused_existing']}")
        print(f"Existing files skipped: {self.stats['skipped_existing']}")
        print(f"Failed conversions:     {self.stats['failed']}")
        if self.dry_run:
            print(f"Dry-run actions:        {self.stats['dry_run_actions']}")

        if self.enable_metadata:
            print("\nMETADATA SOURCES:")
            print(f"Already complete:       {self.stats['metadata_complete']}")
            print(f"MusicBrainz lookup:     {self.stats['metadata_found']}")
            print(f"Audio fingerprinting:   {self.stats['metadata_fingerprint']}")
            print(f"Last.fm search:         {self.stats['metadata_lastfm']}")
            print(f"Directory structure:    {self.stats['metadata_fallback']}")

        print("\nTIMING:")
        print(f"Total time elapsed:     {elapsed/60:.1f} minutes")
        print(f"Average time per file:  {elapsed/max(1, self.stats['total_files']):.1f} seconds")

        if self.stats["total_files"] > 0:
            success_rate = ((self.stats["total_files"] - self.stats["failed"]) / self.stats["total_files"]) * 100
            print(f"Success rate:           {success_rate:.1f}%")

        print(f"\nOutput location: {self.output_path}")
        print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Enhanced WAV to FLAC Converter with Advanced Metadata Lookup and Audio Fingerprinting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python wav_to_flac_converter.py "C:\\Music\\WAV Files"
  python wav_to_flac_converter.py "/path/to/wav/files" --compatibility
  python wav_to_flac_converter.py "./music" --basic-metadata
  python wav_to_flac_converter.py "./music" --no-metadata
  python wav_to_flac_converter.py "./music" --dry-run
  python wav_to_flac_converter.py "./music" --cache-file metadata-cache.json
  python wav_to_flac_converter.py "./music" --aggressive-metadata --fingerprinting

Features:
  - Intelligent metadata lookup for international artists
  - Album-based track matching for generic filenames
  - Multiple fallback strategies for metadata
  - Smart directory structure parsing
  - Rate-limited MusicBrainz API usage with caching
  - Audio fingerprinting for unknown tracks
  - Skip conversion for existing FLAC files
  - Only lookup metadata if incomplete
        """,
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    parser.add_argument("source_path", help="Path to the directory containing WAV/FLAC files")

    parser.add_argument(
        "--output",
        "-o",
        default="FLAC CONVERTER",
        help='Output folder/path. Relative paths are created next to the source folder (default: "FLAC CONVERTER")',
    )

    parser.add_argument(
        "--compatibility",
        "-c",
        action="store_true",
        help="Use compatibility mode (16-bit, compression level 8) for better device support",
    )

    metadata_group = parser.add_mutually_exclusive_group()
    metadata_group.add_argument(
        "--basic-metadata",
        "-b",
        action="store_true",
        help="Use only directory/file names for metadata; skip MusicBrainz, Last.fm, and AcoustID lookups",
    )

    metadata_group.add_argument("--no-metadata", "-n", action="store_true", help="Disable metadata embedding entirely")

    parser.add_argument(
        "--aggressive-metadata",
        "-a",
        action="store_true",
        help="Use aggressive metadata search (more API calls, better results)",
    )

    parser.add_argument(
        "--fingerprinting",
        "-f",
        action="store_true",
        help="Force-enable audio fingerprinting for unknown tracks (requires internet and an AcoustID API key)",
    )

    parser.add_argument(
        "--no-fingerprinting", action="store_true", help="Disable audio fingerprinting even if metadata is enabled"
    )

    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--overwrite", action="store_true", help="Replace existing output audio files")

    output_group.add_argument(
        "--skip-existing", action="store_true", help="Skip files whose output path already exists"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned actions without creating directories, converting files, or writing metadata",
    )

    parser.add_argument(
        "--cache-file",
        help='Persistent metadata cache file (default: ".metadata_cache.json" in the output folder)',
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable persistent metadata lookup caching",
    )

    parser.add_argument(
        "--log-file",
        default="conversion_enhanced.log",
        help='Conversion log file path (default: "conversion_enhanced.log")',
    )

    args = parser.parse_args()
    configure_logging(args.log_file)

    # Determine fingerprinting setting. Fingerprinting is enabled automatically when
    # an AcoustID key is configured, or explicitly with --fingerprinting.
    acoustid_key_configured = has_acoustid_key()
    enable_fingerprinting = (
        (args.fingerprinting or acoustid_key_configured)
        and not args.no_fingerprinting
        and not args.no_metadata
        and not args.basic_metadata
    )

    if enable_fingerprinting and not acoustid_key_configured:
        logger.error("Audio fingerprinting requires ACOUSTID_API_KEY. See ACOUSTID_SETUP.md.")
        sys.exit(1)

    missing_dependencies = get_missing_dependencies(
        enable_metadata=not args.no_metadata,
        basic_metadata=args.basic_metadata,
        enable_fingerprinting=enable_fingerprinting,
        dry_run=args.dry_run,
    )
    if missing_dependencies:
        missing = ", ".join(missing_dependencies)
        logger.error(f"Missing Python dependencies for this mode: {missing}")
        logger.error("Install them with: python -m pip install -r requirements.txt")
        sys.exit(1)

    try:
        converter = EnhancedWAVToFLACConverter(
            source_path=args.source_path,
            output_folder=args.output,
            compatibility_mode=args.compatibility,
            enable_metadata=not args.no_metadata,
            aggressive_metadata=args.aggressive_metadata,
            enable_fingerprinting=enable_fingerprinting,
            basic_metadata=args.basic_metadata,
            overwrite=args.overwrite,
            skip_existing=args.skip_existing,
            dry_run=args.dry_run,
            cache_file=args.cache_file,
            use_persistent_cache=not args.no_cache,
        )

        converted, failed = converter.convert_all()
        converter.print_summary()

        # Exit with appropriate code
        sys.exit(0 if failed == 0 else 1)

    except KeyboardInterrupt:
        logger.info("\nConversion interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
