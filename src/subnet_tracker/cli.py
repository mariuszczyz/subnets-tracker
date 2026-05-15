import boto3
import click
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .tracker import SubnetTracker
from .visualizer import generate_multi_vpc_visualization, generate_visualization, open_visualization

console = Console()


@click.command()
@click.option('--vpc-id', default=None, help='The VPC ID to analyze.')
@click.option('--region', default='us-east-1', help='AWS region.')
@click.option('--visual', is_flag=True, default=False, help='Generate an interactive HTML visualization.')
@click.option('--multi-vpc', is_flag=True, default=False, help='Visualize all VPCs in the region.')
@click.option('--output-dir', default=None, help='Directory to write the visualization file.')
@click.option('--no-open', is_flag=True, default=False, help='Write the HTML file without opening it in a browser.')
def main(vpc_id, region, visual, multi_vpc, output_dir, no_open):
    """AWS Subnet Tracker: Analyze VPC subnets and IP usage."""

    if multi_vpc:
        _run_multi_vpc(region, output_dir, no_open)
        return

    if not vpc_id:
        _run_all_vpcs_report(region)
        return

    console.print(f"[bold blue]Analyzing VPC:[/bold blue] {vpc_id} in [bold green]{region}[/bold green]\n")

    tracker = SubnetTracker(vpc_id, region)
    try:
        tracker.fetch_data()
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}")
        sys.exit(1)

    if visual:
        filepath = generate_visualization(
            vpc_data=tracker.vpc_data,
            subnets=tracker.subnets,
            vpc_id=vpc_id,
            output_dir=output_dir,
        )
        console.print(f"[bold green]Visualization saved to:[/bold green] {filepath}")
        if not no_open:
            open_visualization(filepath)
        return

    _print_tables(tracker)


def _run_multi_vpc(region: str, output_dir: str | None, no_open: bool) -> None:
    ec2 = boto3.client('ec2', region_name=region)
    all_vpcs = ec2.describe_vpcs()['Vpcs']

    paginator = ec2.get_paginator('describe_subnets')
    for vpc in all_vpcs:
        vpc['Subnets'] = [
            sn
            for page in paginator.paginate(Filters=[{'Name': 'vpc-id', 'Values': [vpc['VpcId']]}])
            for sn in page['Subnets']
        ]

    filepath = generate_multi_vpc_visualization(vpcs_data=all_vpcs, output_dir=output_dir)
    console.print(f"[bold green]Multi-VPC visualization saved to:[/bold green] {filepath}")
    if not no_open:
        open_visualization(filepath)


def _run_all_vpcs_report(region: str) -> None:
    ec2 = boto3.client('ec2', region_name=region)
    vpcs = ec2.describe_vpcs()['Vpcs']
    if not vpcs:
        console.print(f"[yellow]No VPCs found in region {region}.[/yellow]")
        return
    for vpc in vpcs:
        vpc_id = vpc['VpcId']
        cidr = vpc.get('CidrBlock', 'N/A')
        console.rule(f"VPC: {vpc_id}  ({cidr})")
        try:
            tracker = SubnetTracker(vpc_id, region)
            tracker.fetch_data()
            _print_tables(tracker)
        except Exception as e:
            console.print(f"[bold red]Error fetching VPC {vpc_id}:[/bold red] {e}")


def _print_tables(tracker: SubnetTracker) -> None:
    details = tracker.get_subnet_details()

    table = Table(title="Subnet Inventory", show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("AZ")
    table.add_column("Type")
    table.add_column("CIDR")
    table.add_column("Total IPs", justify="right")
    table.add_column("Used IPs", justify="right")
    table.add_column("Available IPs", justify="right")
    table.add_column("EKS Tags", justify="center")

    for d in details:
        eks_tags = []
        if d['eks_internal_elb']:
            eks_tags.append("[blue]Internal[/blue]")
        if d['eks_elb']:
            eks_tags.append("[green]External[/green]")
        eks_tags_str = ", ".join(eks_tags) if eks_tags else "[grey50]None[/grey50]"
        type_style = "green" if d['type'] == 'Public' else 'blue'

        table.add_row(
            d['id'],
            d['name'],
            d['az'],
            f"[{type_style}]{d['type']}[/{type_style}]",
            d['cidr'],
            str(d['total_ips']),
            str(d['used_ips']),
            str(d['available_ips']),
            eks_tags_str,
        )

    console.print(table)

    unallocated = tracker.get_unallocated_space()
    if unallocated:
        unalloc_table = Table(title="Unallocated VPC Space", show_header=True, header_style="bold yellow")
        unalloc_table.add_column("CIDR Block")
        for cidr in unallocated:
            unalloc_table.add_row(cidr)
        console.print(unalloc_table)
    else:
        console.print("\n[yellow]No unallocated space found in VPC.[/yellow]")

    recommendations = tracker.get_eks_recommendations()
    rec_style = "green" if recommendations['status'] == 'OK' else 'yellow'
    rec_content = ""

    if recommendations['issues']:
        rec_content += "[bold red]Issues Identified:[/bold red]\n"
        for issue in recommendations['issues']:
            rec_content += f"- {issue}\n"

    if recommendations['proposals']:
        rec_content += "\n[bold blue]Proposals:[/bold blue]\n"
        for proposal in recommendations['proposals']:
            rec_content += f"- {proposal}\n"

    if not recommendations['issues'] and not recommendations['proposals']:
        rec_content = "[green]All EKS networking best practices are followed![/green]"

    console.print(Panel(
        rec_content,
        title=f"EKS Recommendations ([{rec_style}]{recommendations['status']}[/{rec_style}])",
        expand=False,
    ))


if __name__ == '__main__':
    main()
