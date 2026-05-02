#!/usr/bin/env python3
"""
Descript Integration Tool
Text-based video editing via MCP server or REST API

Two ways to use Descript:
1. MCP Server (Recommended): Direct control from Claude desktop app
2. REST API: Programmatic access via Python

MCP Setup: https://help.descript.com/hc/en-us/articles/45008080343053
API Docs: https://docs.descriptapi.com
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    import requests
except ImportError:
    print("Required packages not found. Install with:")
    print("  pip install requests python-dotenv")
    sys.exit(1)


# MCP Server URL (for Claude desktop app connector)
MCP_SERVER_URL = "https://api.descript.com/v2/mcp"

# REST API Base URL
API_BASE_URL = "https://api.descript.com/v2"


class DescriptAPI:
    """Descript REST API client for programmatic access"""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Descript API client

        Args:
            api_key: Descript API key (or from DESCRIPT_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("DESCRIPT_API_KEY")
        if not self.api_key:
            raise ValueError(
                "DESCRIPT_API_KEY not found. "
                "Set environment variable or use MCP connector instead.\n"
                "Get API key from: https://docs.descriptapi.com"
            )

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make API request"""
        url = f"{API_BASE_URL}{endpoint}"
        try:
            response = requests.request(method, url, json=data, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"API request failed: {e}")

    def list_projects(self, drive_id: Optional[str] = None) -> List[Dict]:
        """List projects in a Drive"""
        endpoint = "/projects"
        if drive_id:
            endpoint = f"/drives/{drive_id}/projects"
        result = self._request("GET", endpoint)
        return result.get("projects", [])

    def get_project(self, project_id: str) -> Dict:
        """Get project details"""
        return self._request("GET", f"/projects/{project_id}")

    def import_media(
        self,
        url: str,
        project_id: Optional[str] = None,
        folder_id: Optional[str] = None
    ) -> Dict:
        """Import media from URL into a project

        Args:
            url: Public URL of media to import
            project_id: Target project ID (creates new if None)
            folder_id: Optional folder ID

        Returns:
            Job status
        """
        data = {"url": url}
        if project_id:
            data["project_id"] = project_id
        if folder_id:
            data["folder_id"] = folder_id

        return self._request("POST", "/imports", data)

    def apply_underlord(
        self,
        project_id: str,
        composition_id: str,
        actions: List[str]
    ) -> Dict:
        """Apply Underlord editing actions

        Args:
            project_id: Project ID
            composition_id: Composition ID within project
            actions: List of actions (e.g., "transcribe", "remove_filler_words", "studio_sound")

        Returns:
            Job status
        """
        return self._request("POST", f"/projects/{project_id}/compositions/{composition_id}/underlord", {
            "actions": actions
        })

    def publish_project(
        self,
        project_id: str,
        composition_id: str,
        share_settings: Optional[Dict] = None
    ) -> Dict:
        """Publish project and get share link

        Args:
            project_id: Project ID
            composition_id: Composition ID
            share_settings: Optional share settings

        Returns:
            Published project info with share URL
        """
        data = share_settings or {}
        return self._request("POST", f"/projects/{project_id}/compositions/{composition_id}/publish", data)


def show_mcp_setup():
    """Display MCP server setup instructions"""
    print("=" * 70)
    print("Descript MCP Server Setup for Claude Desktop App")
    print("=" * 70)
    print()
    print("The Descript MCP server lets Claude directly control Descript.")
    print("No API token needed — you'll sign in via OAuth during setup.")
    print()
    print("BEFORE STARTING:")
    print("  • Use Claude desktop app (not web)")
    print("  • Use Chat mode (not Cowork)")
    print("  • Enable Settings → Capabilities → Network egress & Code execution")
    print("  • Ensure access to Customize → Connectors")
    print()
    print("SETUP STEPS:")
    print("  1. Open Claude desktop app")
    print("  2. Navigate to Customize → Connectors")
    print("  3. Click + to add custom connector")
    print("  4. Enter:")
    print("     • Name: Descript")
    print(f"     • Remote MCP server URL: {MCP_SERVER_URL}")
    print("  5. Click Connect, sign in to Descript")
    print("  6. Allow access (connects to your current Drive)")
    print()
    print("ONCE CONNECTED, Claude can:")
    print("  • Import media from URLs or your computer")
    print("  • Transcribe, add captions, remove filler words")
    print("  • Apply Studio Sound enhancement")
    print("  • Create highlight reels")
    print("  • Find and manage projects")
    print("  • Publish and get share links")
    print()
    print("EXAMPLE PROMPTS (in Claude Chat mode):")
    print('  • "Import this video from my desktop into my Podcasts folder and transcribe it"')
    print('  • "Add Studio Sound and remove filler words from the second composition"')
    print('  • "Find my Q2 Review project and create a 60-second highlight reel"')
    print('  • "Write a script about how to make great coffee, turn it into a video, and publish it"')
    print()
    print("LIMITATIONS:")
    print("  • Local export not supported (use Descript app directly)")
    print("  • YouTube URLs not supported for import")
    print("  • Job history available for 30 days")
    print()
    print("For help: https://help.descript.com/hc/en-us/articles/45008080343053")
    print("=" * 70)


def show_workflows():
    """Display example workflows"""
    print("=" * 70)
    print("Descript Video Editing Workflows")
    print("=" * 70)
    print()
    print("WORKFLOW 1: Text-Based Editing (MCP)")
    print("-" * 70)
    print("1. Import footage: 'Import race_footage.mp4 into a new project'")
    print("2. Transcribe: 'Transcribe the audio and show me the transcript'")
    print("3. Edit: 'Delete all sections where they say um or uh'")
    print("4. Enhance: 'Apply Studio Sound to fix the audio quality'")
    print("5. Export: 'Publish this so I can share it'")
    print()
    print("WORKFLOW 2: Highlight Reel Creation")
    print("-" * 70)
    print("1. Import long footage")
    print("2. Ask Claude: 'Create a 60-second highlight reel with the most exciting moments'")
    print("3. Review and refine")
    print("4. Add captions: 'Add burned-in captions for Instagram'")
    print("5. Export for social media")
    print()
    print("WORKFLOW 3: Podcast Editing")
    print("-" * 70)
    print("1. Import audio/video recording")
    print("2. 'Remove all filler words and silence longer than 2 seconds'")
    print("3. 'Add intro music from my library'")
    print("4. 'Generate a title and description based on the content'")
    print("5. Publish to podcast platform")
    print()
    print("WORKFLOW 4: Documentary Assembly")
    print("-" * 70)
    print("1. Import multiple interview clips")
    print("2. 'Transcribe all clips and find soundbites about transmission rebuild'")
    print("3. 'Create a new composition with those soundbites in chronological order'")
    print("4. Import B-roll footage")
    print("5. 'Add B-roll to support each soundbite'")
    print()
    print("=" * 70)


def show_api_info():
    """Display REST API information"""
    print("=" * 70)
    print("Descript REST API")
    print("=" * 70)
    print()
    print("For programmatic access without Claude, use the REST API.")
    print()
    print("SETUP:")
    print("  1. Get API key: https://docs.descriptapi.com")
    print("  2. Set environment variable:")
    print("     export DESCRIPT_API_KEY=your_key_here")
    print()
    print("ENDPOINTS:")
    print("  GET  /projects              - List projects")
    print("  GET  /projects/{id}         - Get project details")
    print("  POST /imports               - Import media from URL")
    print("  POST /underlord             - Apply AI editing actions")
    print("  POST /publish               - Publish project")
    print()
    print("API DOCS: https://docs.descriptapi.com")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Descript integration for text-based video editing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show MCP setup instructions
  python mcp.py --mcp-setup

  # Show workflow examples
  python mcp.py --workflows

  # List projects via API
  python mcp.py --list-projects

  # Import media via API
  python mcp.py --import-url https://example.com/video.mp4

MCP (Recommended): Use Claude desktop app with MCP connector
API: For programmatic access via Python
        """
    )

    # Info
    parser.add_argument("--mcp-setup", action="store_true",
                       help="Show MCP server setup instructions for Claude")
    parser.add_argument("--workflows", action="store_true",
                       help="Show example editing workflows")
    parser.add_argument("--api-info", action="store_true",
                       help="Show REST API information")

    # API operations
    parser.add_argument("--list-projects", action="store_true",
                       help="List all projects (requires API key)")
    parser.add_argument("--get-project",
                       help="Get project details by ID (requires API key)")
    parser.add_argument("--import-url",
                       help="Import media from URL (requires API key)")
    parser.add_argument("--project-id",
                       help="Target project ID for import")
    parser.add_argument("--folder-id",
                       help="Target folder ID for import")

    args = parser.parse_args()

    if args.mcp_setup:
        show_mcp_setup()
        return

    if args.workflows:
        show_workflows()
        return

    if args.api_info:
        show_api_info()
        return

    # API operations
    try:
        client = DescriptAPI()
    except ValueError as e:
        print(f"Error: {e}")
        print("\nUse --mcp-setup to configure MCP connector")
        print("Use --api-info for REST API setup")
        return

    if args.list_projects:
        projects = client.list_projects()
        print(f"Found {len(projects)} projects:")
        for p in projects:
            print(f"  {p.get('id')}: {p.get('name')}")

    elif args.get_project:
        project = client.get_project(args.get_project)
        print(json.dumps(project, indent=2))

    elif args.import_url:
        result = client.import_media(
            url=args.import_url,
            project_id=args.project_id,
            folder_id=args.folder_id
        )
        print(f"Import job started:")
        print(json.dumps(result, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
