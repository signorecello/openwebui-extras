"""
title: YouTube Transcript Fetcher
author: RVCKVS
description: Fetches YouTube video transcripts using the video URL without needing an API key.
required_open_webui_version: 0.4.0
source: https://gist.github.com/signorecello/04a44ca18ae1b80520b93e62a71ecd26
requirements: requests
version: 1.0.1
licence: MIT
"""

# All credit due to RVCKVS, would make a PR to fix the regex into the original impl but couldn't find a repo, so here it is
# the only change I made was updating the regex to match videos in the `youtu.be/<something>` format instead of `/watch?v=<something>

import requests
import re
import xml.etree.ElementTree as ET
from pydantic import BaseModel, Field


class Tools:
    class UserValves(BaseModel):
        """
        User-configurable parameters.
        """

        language: str = Field(
            "en", description="Preferred transcript language (default: en)"
        )

    def __init__(self):
        """Initialize the tool with user-configurable valves."""
        self.user_valves = self.UserValves()

    async def fetch_youtube_transcript(
        self, video_url: str, __event_emitter__=None
    ) -> str:
        """
        Fetches the transcript of a YouTube video given its URL without an API key.

        :param video_url: The URL of the YouTube video
        :return: The video transcript as a string
        """

        # Notify user about the extraction process
        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Extracting video ID...", "done": False},
            }
        )
        video_id = self.extract_video_id(video_url)
        if not video_id:
            return "Invalid YouTube URL"

        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Fetching video page...", "done": False},
            }
        )
        try:
            response = requests.get(f"https://www.youtube.com/watch?v={video_id}")
            response.raise_for_status()
        except requests.RequestException as e:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": "Failed to fetch video", "done": True},
                }
            )
            return f"Failed to fetch YouTube video page: {e}"

        body = response.text

        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Extracting captions data...", "done": False},
            }
        )
        start_index = body.find('"captionTracks":')
        if start_index == -1:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": "No captions available", "done": True},
                }
            )
            return "No captions found for video"

        end_index = body.find("]", start_index)
        if end_index == -1:
            return "Invalid captions data"

        captions_data = body[start_index : end_index + 1]
        caption_url = self.extract_caption_url(captions_data)

        if not caption_url:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": "No English captions found", "done": True},
                }
            )
            return "No suitable captions found"

        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Downloading transcript...", "done": False},
            }
        )
        try:
            caption_response = requests.get(caption_url)
            caption_response.raise_for_status()
        except requests.RequestException as e:
            return f"Failed to fetch transcript: {e}"

        transcript = self.extract_transcript_from_xml(caption_response.text)
        if not transcript:
            return "Transcript extraction failed"

        await __event_emitter__(
            {
                "type": "status",
                "data": {
                    "description": "Transcript fetched successfully!",
                    "done": True,
                },
            }
        )

        # Send the transcript back to the LLM for further processing
        await __event_emitter__(
            {
                "type": "message",
                "data": {"content": f"Transcript has been fetched!\n\n"},
            }
        )

        # Returning the transcript so the LLM can also process it internally
        return f"Here's the transcript, : {transcript}.\n\n"

    def extract_transcript_from_xml(self, xml_content: str) -> str:
        """
        Extracts readable text from YouTube XML captions.

        :param xml_content: The XML content of the captions
        :return: The cleaned transcript text
        """
        try:
            root = ET.fromstring(xml_content)
            transcript_lines = [
                text.text.replace("&#39;", "'").replace("&amp;", "&")
                for text in root.findall(".//text")
            ]
            return " ".join(transcript_lines)
        except ET.ParseError:
            return ""

    def extract_video_id(self, url: str) -> str:
        """
        Extract YouTube video ID from URL.

        :param url: The YouTube video URL
        :return: Extracted video ID or empty string if invalid
        """
        match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
        return match.group(1) if match else ""

    def extract_caption_url(self, captions_data: str) -> str:
        """
        Extracts the caption URL from captions metadata.

        :param captions_data: The caption metadata string
        :return: Extracted caption URL or empty string
        """
        url_start = captions_data.find('"baseUrl":"')
        if url_start == -1:
            return ""

        url_start += len('"baseUrl":"')
        url_end = captions_data.find('"', url_start)
        if url_end == -1:
            return ""

        return captions_data[url_start:url_end].replace("\\u0026", "&")
