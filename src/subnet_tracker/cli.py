import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from .tracker import SubnetTracker
from .visualizer import generate_visualization, generate_multi_vpc_visualization, open_visualization
from pathlib import Path
import sys

console = Console()

@click.command()
@click.option('--vpc-id', required=True, help='The VPC ID to analyze.')
@click.option('--region', default='us-east-1', help='AWS region.')
@click.option('--visual', is_flag=True, default=False, help='Generate an interactive HTML visualization.')
@click.option('--multi-vpc', is_flag=True, default=False, help='Analyze all VPCs in the region.')
@click.option('--output-dir', default=None, help='Directory to write the visualization file.')
def main(vpc_id, region, visual, multi_vpc, output_dir):
    """
    AWS Subnet Tracker: Analyze VPC subnets and IP usage.
    """
    console.print(f"[bold blue]Analyzing VPC:[/bold blue] {vpc_id} in [bold green]{region}[/bold green]\n")

    tracker = SubnetTracker(vpc_id, region)

    try:
        tracker.fetch_data()
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}")
        sys.exit(1)

    if visual:
        # Generate HTML visualization
        filepath = generate_visualization(
            vpc_data=tracker.vpc_data,
            subnets=tracker.subnets,
            vpc_id=vpc_id,
            output_dir=output_dir,
        )
        console.print(f"[bold green]Visualization saved to:[/bold green] {filepath}")
        open_visualization(filepath)
        return

    if multi_vpc:
        # Multi-VPC mode: analyze all VPCs
        all_vpcs = tracker.ec2.describe_vpcs()['Vpcs']
        filepath = generate_multi_vpc_visualization(
            vpcs_data=all_vpcs,
            output_dir=output_dir,
        )
        console.print(f"[bold green]Multi-VPC visualization saved to:[/bold green] {filepath}")
        open_visualization(filepath)
        return

    # Table 1: Subnet Inventory
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
        if d['eks_internal_elb']: eks_tags.append("[blue]Internal[/blue]")
        if d['eks_elb']: eks_tags.append("[green]External[/green]")
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
            eks_tags_str
        )

    console.print(table)

    # Table 2: Unallocated VPC Space
    unallocated = tracker.get_unallocated_space()
    if unallocated:
        unalloc_table = Table(title="Unallocated VPC Space", show_header=True, header_style="bold yellow")
        unalloc_table.add_column("CIDR Block")
        for cidr in unallocated:
            unalloc_table.add_row(cidr)
        console.print(unalloc_table)
    else:
        console.print("\n[yellow]No unallocated space found in VPC.[/yellow]")

    # Table 3: EKS Recommendations
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

    console.print(Panel(rec_content, title=f"EKS Recommendations ([{rec_style}]{recommendations['status']}[/{rec_style}])", expand=False))

if __name__ == '__main__':
    main()
