"""
Circo Video Sense — CLI Entry Point

Usage:
    video-sense serve [--local] [--port PORT] [--workers N]
    video-sense analyze <video-path> [--tier TIER] [--pipeline VERSION]
    video-sense health [--json] [--port PORT]
    video-sense version
"""

import click
import json
import os
import sys

from src import __version__


@click.group()
def main():
    """Circo Video Sense — AI Creative Intelligence Engine."""
    pass


@main.command()
@click.option("--local", is_flag=True, default=False, help="Force local mode (mock AI, no Kafka)")
@click.option("--port", default=8000, type=int, help="Port to listen on")
@click.option("--workers", default=1, type=int, help="Number of Gunicorn workers (production only)")
def serve(local, port, workers):
    """Start the Video Sense server."""
    import uvicorn

    if local:
        os.environ["LOCAL_MODE"] = "true"
        click.echo(f"Starting Video Sense v{__version__} in LOCAL mode on port {port}...")
        uvicorn.run(
            "main_local:app",
            host="0.0.0.0",
            port=port,
            reload=True,
            log_level="info",
        )
    else:
        env = os.getenv("NODE_ENV", "development")
        click.echo(f"Starting Video Sense v{__version__} ({env}) on port {port} with {workers} workers...")
        if env == "production":
            import subprocess
            cmd = [
                "gunicorn",
                "main:app",
                "--bind", f"0.0.0.0:{port}",
                "--workers", str(workers),
                "--log-level", os.getenv("LOG_LEVEL", "info"),
                "-k", "uvicorn.workers.UvicornWorker",
            ]
            subprocess.run(cmd, check=True)
        else:
            uvicorn.run(
                "main_local:app",
                host="0.0.0.0",
                port=port,
                reload=True,
                log_level="info",
            )


@main.command()
@click.argument("video_path", type=click.Path(exists=True))
@click.option("--tier", default="free", type=click.Choice(["free", "plus", "pro", "enterprise"]), help="Monetization tier")
@click.option("--pipeline", "pipeline_version", default="v1.1", type=click.Choice(["v0", "v1", "v1.1"]), help="Pipeline version")
@click.option("--output", default=None, type=click.Path(), help="Output directory for clips/teasers")
def analyze(video_path, tier, pipeline_version, output):
    """Run Video Sense pipeline on a local video file (no server required)."""
    # Stub — will be fully implemented in Phase 6
    click.echo(f"analyze: not yet implemented (video={video_path}, tier={tier}, pipeline={pipeline_version})")
    click.echo("This command will be available after Phase 6.")
    sys.exit(1)


@main.command()
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON")
@click.option("--port", default=8000, type=int, help="Server port to check")
def health(as_json, port):
    """Check if the Video Sense server is running."""
    import urllib.request
    import urllib.error

    url = f"http://localhost:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if as_json:
                click.echo(json.dumps(data, indent=2))
            else:
                status = data.get("status", "unknown")
                mode = data.get("mode", "unknown")
                click.echo(f"Status: {status}")
                click.echo(f"Mode: {mode}")
    except urllib.error.URLError:
        if as_json:
            click.echo(json.dumps({"status": "unreachable", "url": url}))
        else:
            click.echo(f"Server not reachable at {url}")
        sys.exit(1)


@main.command()
def version():
    """Print version information."""
    click.echo(f"video-sense {__version__}")
    click.echo(f"Python {sys.version.split()[0]}")


if __name__ == "__main__":
    main()
