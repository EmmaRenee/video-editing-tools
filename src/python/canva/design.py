#!/usr/bin/env python3
"""
Canva Connect API Integration
Automate motion graphics, intros, lower thirds generation

Requirements:
    pip install requests python-dotenv

API Setup: https://www.canva.dev/developers/connect/api
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional

try:
    from dotenv import load_dotenv
    import requests
except ImportError:
    print("Required packages not found. Install with:")
    print("  pip install requests python-dotenv")
    sys.exit(1)

# Load environment variables
load_dotenv()

# Canva API endpoints
BASE_URL = "https://www.canva.dev/api/connect"
AUTH_URL = "https://www.canva.dev/api/connect/oauth"


class CanvaDesign:
    """Automate Canva designs via Connect API"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        refresh_token: Optional[str] = None
    ):
        """Initialize Canva client

        Args:
            api_key: Canva API key (or from CANVA_API_KEY env var)
            refresh_token: OAuth refresh token (or from CANVA_REFRESH_TOKEN env var)
        """
        self.api_key = api_key or os.getenv("CANVA_API_KEY")
        self.refresh_token = refresh_token or os.getenv("CANVA_REFRESH_TOKEN")

        if not self.api_key:
            print("Warning: CANVA_API_KEY not found. Some features may be limited.")

        self.access_token = None
        if self.refresh_token:
            self.access_token = self._refresh_access_token()

    def _refresh_access_token(self) -> str:
        """Refresh OAuth access token"""
        if not self.refresh_token:
            return None

        response = requests.post(
            f"{AUTH_URL}/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.api_key,
            }
        )

        if response.status_code == 200:
            data = response.json()
            return data.get("access_token")
        return None

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Dict = None,
        headers: Dict = None
    ) -> Dict:
        """Make API request with error handling"""
        url = f"{BASE_URL}{endpoint}"

        default_headers = {}
        if self.access_token:
            default_headers["Authorization"] = f"Bearer {self.access_token}"

        if headers:
            default_headers.update(headers)

        try:
            response = requests.request(
                method,
                url,
                json=data,
                headers=default_headers
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"API request failed: {e}")

    def list_designs(self, folder_id: Optional[str] = None) -> List[Dict]:
        """List designs in a folder or all designs

        Args:
            folder_id: Optional folder ID to filter by

        Returns:
            List of design metadata
        """
        endpoint = "/v1/designs"
        if folder_id:
            endpoint = f"/v1/folders/{folder_id}/designs"

        result = self._request("GET", endpoint)
        return result.get("data", [])

    def get_design(self, design_id: str) -> Dict:
        """Get design details by ID

        Args:
            design_id: Canva design ID

        Returns:
            Design metadata
        """
        result = self._request("GET", f"/v1/designs/{design_id}")
        return result.get("data", {})

    def create_design_from_template(
        self,
        template_id: str,
        design_data: Dict,
        output_name: str = "Auto Generated Design"
    ) -> str:
        """Create design from template with data autofill

        Args:
            template_id: Template design ID
            design_data: Dictionary of field names to values
            output_name: Name for the created design

        Returns:
            Design ID of created design
        """
        print(f"Creating design from template: {template_id}")

        response = self._request("POST", "/v1/designs", {
            "template_id": template_id,
            "name": output_name,
            "data": design_data
        })

        design_id = response.get("data", {}).get("id")
        print(f"Design created: {design_id}")
        return design_id

    def export_design(
        self,
        design_id: str,
        output_file: str,
        export_format: str = "mp4",
        quality: str = "standard"
    ) -> str:
        """Export design as file

        Args:
            design_id: Canva design ID
            output_file: Output file path
            export_format: Format (mp4, png, jpg, pdf)
            quality: Export quality (draft, standard, high)

        Returns:
            Path to downloaded file
        """
        print(f"Exporting design: {design_id} as {export_format}")

        # Start export job
        export_response = self._request("POST", f"/v1/designs/{design_id}/exports", {
            "format": export_format,
            "quality": quality
        })

        job_id = export_response.get("data", {}).get("job_id")
        if not job_id:
            raise RuntimeError("Failed to start export job")

        print(f"Export job: {job_id}")
        print("Waiting for export...")

        # Poll for completion
        while True:
            status_response = self._request("GET", f"/v1/designs/{design_id}/exports/{job_id}")
            status = status_response.get("data", {}).get("status")

            if status == "success":
                break
            elif status == "failed":
                raise RuntimeError("Export failed")
            elif status in ("pending", "in_progress"):
                print(f"  Status: {status}...")
                time.sleep(5)

        # Get export URL
        export_url = status_response.get("data", {}).get("url")
        if not export_url:
            raise RuntimeError("No export URL in response")

        # Download file
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"Downloading to: {output_path}")
        file_data = requests.get(export_url).content
        with open(output_path, 'wb') as f:
            f.write(file_data)

        print(f"Export saved: {output_path}")
        return str(output_path)

    def create_lower_third(
        self,
        name: str,
        role: str,
        template_id: Optional[str] = None,
        output_file: str = "lower_third.png"
    ) -> str:
        """Create lower third graphic

        Args:
            name: Person's name
            role: Person's role/title
            template_id: Optional template ID
            output_file: Output file path

        Returns:
            Path to generated file
        """
        if not template_id:
            # Use a default approach - save data for manual application
            print("No template ID provided. Saving design data...")
            data_file = Path(output_file).with_suffix(".json")
            with open(data_file, 'w') as f:
                json.dump({"name": name, "role": role}, f, indent=2)
            print(f"Design data saved to: {data_file}")
            print("Apply this data manually in Canva or provide a template_id.")
            return str(data_file)

        design_id = self.create_design_from_template(
            template_id=template_id,
            design_data={"name": name, "role": role},
            output_name=f"Lower Third: {name}"
        )

        return self.export_design(design_id, output_file, export_format="png")

    def create_intro(
        self,
        title: str,
        subtitle: str = "",
        template_id: Optional[str] = None,
        output_file: str = "intro.mp4"
    ) -> str:
        """Create intro animation

        Args:
            title: Main title text
            subtitle: Optional subtitle
            template_id: Optional template ID
            output_file: Output file path

        Returns:
            Path to generated file
        """
        if not template_id:
            data_file = Path(output_file).with_suffix(".json")
            with open(data_file, 'w') as f:
                json.dump({"title": title, "subtitle": subtitle}, f, indent=2)
            print(f"Design data saved to: {data_file}")
            print("Apply this data manually in Canva or provide a template_id.")
            return str(data_file)

        design_data = {"title": title}
        if subtitle:
            design_data["subtitle"] = subtitle

        design_id = self.create_design_from_template(
            template_id=template_id,
            design_data=design_data,
            output_name=f"Intro: {title}"
        )

        return self.export_design(design_id, output_file, export_format="mp4")


class LocalDesignGenerator:
    """Generate design data files for manual Canva application

    Use this when API access is not configured.
    """

    @staticmethod
    def create_lower_third(name: str, role: str, output_dir: str = "designs") -> str:
        """Create lower third design data file

        Args:
            name: Person's name
            role: Person's role/title
            output_dir: Directory for design files

        Returns:
            Path to JSON design file
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        safe_name = name.lower().replace(" ", "_")
        file_path = output_path / f"lower_third_{safe_name}.json"

        design_data = {
            "type": "lower_third",
            "name": name,
            "role": role,
            "timestamp": time.time()
        }

        with open(file_path, 'w') as f:
            json.dump(design_data, f, indent=2)

        print(f"Design data saved: {file_path}")
        return str(file_path)

    @staticmethod
    def create_intro(title: str, subtitle: str = "", output_dir: str = "designs") -> str:
        """Create intro design data file

        Args:
            title: Main title text
            subtitle: Optional subtitle
            output_dir: Directory for design files

        Returns:
            Path to JSON design file
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        safe_title = title.lower().replace(" ", "_").replace("/", "_")[:50]
        file_path = output_path / f"intro_{safe_title}.json"

        design_data = {
            "type": "intro",
            "title": title,
            "subtitle": subtitle,
            "timestamp": time.time()
        }

        with open(file_path, 'w') as f:
            json.dump(design_data, f, indent=2)

        print(f"Design data saved: {file_path}")
        return str(file_path)

    @staticmethod
    def create_batch_from_roster(roster_file: str, output_dir: str = "designs") -> List[str]:
        """Create lower thirds from roster file

        Args:
            roster_file: Path to JSON roster file with name/role pairs
            output_dir: Directory for design files

        Returns:
            List of created file paths
        """
        roster_path = Path(roster_file)
        if not roster_path.exists():
            raise FileNotFoundError(f"Roster file not found: {roster_file}")

        with open(roster_path, 'r') as f:
            roster = json.load(f)

        created = []

        for person in roster:
            name = person.get("name", "")
            role = person.get("role", "")

            if name and role:
                result = LocalDesignGenerator.create_lower_third(name, role, output_dir)
                created.append(result)

        print(f"Created {len(created)} lower third designs")
        return created


def show_templates():
    """Display template categories"""
    print("Canva Template Categories:")
    print("  intro           - Intro animations")
    print("  lower_third     - Name plates/lower thirds")
    print("  end_card        - End screens with CTAs")
    print("  transition      - Transition effects")
    print("  overlay         - Tech/data overlays")
    print()
    print("To use templates:")
    print("1. Find template in Canva")
    print("2. Copy template ID from URL")
    print("3. Use --template-id with design.py")


def main():
    parser = argparse.ArgumentParser(
        description="Canva design automation for motion graphics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create lower third design data
  python design.py --lower-third "Matt Meyer" --role "Technician"

  # Create intro design data
  python design.py --intro "Drive Auto Sports" --subtitle "Transmission Rebuild"

  # Batch create from roster
  python design.py --batch-roster team_roster.json

  # List designs (requires API auth)
  python design.py --list-designs

  # Export design (requires API auth)
  python design.py --export DESIGN_ID --output intro.mp4

Team roster format (JSON):
  [
    {"name": "Matt Meyer", "role": "Technician"},
    {"name": "Paul Carter", "role": "GM & Tuner"},
    {"name": "Michael Bryan", "role": "Technician"}
  ]
        """
    )

    # Design creation
    parser.add_argument("--lower-third", "-l", nargs=2, metavar=("NAME", "ROLE"),
                       help="Create lower third design data")
    parser.add_argument("--intro", "-i", nargs="+", metavar="TITLE",
                       help="Create intro design data (title [subtitle])")

    # Batch operations
    parser.add_argument("--batch-roster", "-b",
                       help="Create lower thirds from roster JSON file")

    # API operations (require auth)
    parser.add_argument("--list-designs", action="store_true",
                       help="List all Canva designs (requires API auth)")
    parser.add_argument("--export", "-e", metavar="DESIGN_ID",
                       help="Export design by ID (requires API auth)")
    parser.add_argument("--template-id", "-t",
                       help="Template ID for design creation")

    # Output options
    parser.add_argument("--output", "-o",
                       help="Output file path")
    parser.add_argument("--output-dir", "-d", default="designs",
                       help="Output directory for design files (default: designs/)")
    parser.add_argument("--format", "-f", default="mp4",
                       choices=["mp4", "png", "jpg", "pdf"],
                       help="Export format (default: mp4)")

    # Utility
    parser.add_argument("--list-templates", action="store_true",
                       help="List template categories")

    args = parser.parse_args()

    if args.list_templates:
        show_templates()
        return

    # Try API client first, fall back to local generator
    try:
        client = CanvaDesign()
        use_api = client.access_token is not None
    except Exception as e:
        print(f"API not available: {e}")
        print("Using local design data generator...")
        use_api = False

    if args.list_designs:
        if use_api:
            designs = client.list_designs()
            print(f"Found {len(designs)} designs:")
            for design in designs[:20]:  # Show first 20
                print(f"  {design.get('id')}: {design.get('name')}")
        else:
            print("Error: API authentication required to list designs")

    elif args.export:
        if use_api:
            output = args.output or f"export.{args.format}"
            client.export_design(args.export, output, args.format)
        else:
            print("Error: API authentication required to export designs")

    elif args.lower_third:
        name, role = args.lower_third
        if use_api and args.template_id:
            output = args.output or "lower_third.png"
            client.create_lower_third(name, role, args.template_id, output)
        else:
            LocalDesignGenerator.create_lower_third(name, role, args.output_dir)

    elif args.intro:
        title = args.intro[0]
        subtitle = args.intro[1] if len(args.intro) > 1 else ""
        if use_api and args.template_id:
            output = args.output or "intro.mp4"
            client.create_intro(title, subtitle, args.template_id, output)
        else:
            LocalDesignGenerator.create_intro(title, subtitle, args.output_dir)

    elif args.batch_roster:
        LocalDesignGenerator.create_batch_from_roster(args.batch_roster, args.output_dir)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
