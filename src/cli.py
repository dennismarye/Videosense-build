"""
Circo Video Sense — CLI Entry Point

Usage:
    video-sense serve [--local] [--port PORT] [--workers N]
    video-sense analyze <video-path> [--tier TIER] [--pipeline VERSION] [--output FILE]
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
@click.option("--pipeline", "pipeline_version", default="v1.2", type=click.Choice(["v0", "v1", "v1.1", "v1.2"]), help="Pipeline version")
@click.option("--output", default=None, type=click.Path(), help="Write JSON result to file")
def analyze(video_path, tier, pipeline_version, output):
    """Run Video Sense pipeline on a local video file (no server required)."""
    import asyncio
    import uuid

    from src.context.context_store import ContextStore
    from src.context.models import JobRequest
    from src.jobs.job_manager import JobManager

    video_path = os.path.abspath(video_path)
    video_id = str(uuid.uuid4())

    click.echo(f"Video Sense v{__version__} — analyzing {os.path.basename(video_path)}")
    click.echo(f"Pipeline: {pipeline_version} | Tier: {tier} | Video ID: {video_id}")

    # Fresh context store per invocation (no shared state)
    context_store = ContextStore()

    # Build the pipeline function based on version
    if pipeline_version == "v0":
        from src.jobs.pipeline import run_v0_pipeline
        pipeline_fn = run_v0_pipeline
    else:
        from src.local.mock_ai_service import MockAIService
        ai_service = MockAIService()

        if pipeline_version == "v1":
            from src.jobs.pipeline_v1 import create_v1_pipeline
            pipeline_fn = create_v1_pipeline(ai_service)
        elif pipeline_version == "v1.1":
            from src.jobs.pipeline_v1_1 import create_v1_1_pipeline
            pipeline_fn = create_v1_1_pipeline(ai_service)
        else:  # v1.2
            from src.jobs.pipeline_v1_2 import create_v1_2_pipeline
            pipeline_fn = create_v1_2_pipeline(ai_service)

    job_manager = JobManager(context_store=context_store, pipeline_fn=pipeline_fn)

    request = JobRequest(
        video_id=video_id,
        source_path=video_path,
        tier=tier,
    )

    try:
        context = asyncio.run(job_manager.submit_and_execute(request))
    except Exception as e:
        click.echo(f"Pipeline failed: {e}", err=True)
        sys.exit(1)

    if context.status.value == "failed":
        click.echo(f"Pipeline completed with status: FAILED", err=True)
        sys.exit(1)

    # Build JSON summary
    summary = {
        "video_id": context.video_id,
        "job_id": context.job_id,
        "status": context.status.value,
        "pipeline": pipeline_version,
        "tier": tier,
        "source": video_path,
        "duration": context.duration,
        "scenes": len(context.scenes),
        "speech_regions": len(context.speech_regions),
    }

    # V1+ fields
    if pipeline_version in ("v1", "v1.1", "v1.2"):
        summary["suggested_clips"] = len(context.suggested_clips)
        summary["topics"] = len(context.topics)
        summary["summary"] = context.summary
        summary["hook_score"] = context.hook_score.score if context.hook_score else None

    # V1.1+ fields
    if pipeline_version in ("v1.1", "v1.2"):
        summary["teasers"] = len(context.teasers)
        summary["platform_bundles"] = len(context.platform_bundles)

    # V1.2 fields
    if pipeline_version == "v1.2":
        summary["content_variants"] = {
            "titles": len(context.content_variants.titles) if context.content_variants else 0,
            "descriptions": len(context.content_variants.descriptions) if context.content_variants else 0,
        }
        summary["thumbnail_crops"] = len(context.thumbnail_crops)
        summary["upload_presets"] = len(context.upload_presets)
        summary["presets_ready"] = sum(1 for p in context.upload_presets if p.ready)

    result_json = json.dumps(summary, indent=2)

    if output:
        output_path = os.path.abspath(output)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(result_json)
        click.echo(f"Result written to {output_path}")
    else:
        click.echo(result_json)


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
