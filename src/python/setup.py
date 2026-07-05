"""
Setup script for videoedit package.

Installation:
    pip install -e .
"""
from pathlib import Path
from setuptools import setup, find_packages

README = (Path(__file__).parent / "README.md").read_text()

setup(
    name="videoedit",
    version="0.2.0",
    description="AI-first video editing pipeline system",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/EmmaRenee/video-editing-tools",
    author="Emma Werner",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "click>=8.0.0",
        "pyyaml>=6.0",
        "textual>=0.50.0",
        "rich>=13.0.0",
    ],
    extras_require={
        "whisper": ["openai-whisper>=20231117"],
        "cloud": ["elevenlabs", "python-dotenv"],
        # Shoot-scale local analysis stack (hybrid funnel tier 1)
        "analyze": [
            "faster-whisper>=1.0",
            "silero-vad>=5.0",
            # scenedetect 0.7 dropped the [opencv] extra; depend on both directly
            "scenedetect>=0.6.3",
            "opencv-python>=4.8",
            "open_clip_torch>=2.24",
            "torch>=2.2",
            "Pillow>=10.0",
            "pillow-heif>=0.15",
            "numpy",
            "onnxruntime",
        ],
        # DaVinci Resolve interchange fallback
        "resolve": ["opentimelineio>=0.16"],
        # Optional analyzers (each degrades gracefully when absent)
        "audio-events": ["panns-inference"],
        "faces": ["mediapipe"],
        "aesthetic": ["pyiqa"],
        "whisper-mlx": ["mlx-whisper"],
    },
    entry_points={
        "console_scripts": [
            "videoedit=videoedit.cli:main",
        ],
    },
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
