import pytest
from moto import mock_aws
import boto3
from botocore.exceptions import ClientError
from subnet_tracker.tracker import SubnetTracker
from click.testing import CliRunner
from subnet_tracker.cli import main

@mock_aws
def test_eks_recommendations_warns_on_missing_elb_tags_only():
    """ELB tag violations alone (no AZ or IP issues) must set status to Warning."""
    ec2 = boto3.client('ec2', region_name='us-east-1')
    vpc = ec2.create_vpc(CidrBlock='10.0.0.0/16')['Vpc']
    vpc_id = vpc['VpcId']

    # Two private subnets in different AZs (satisfies Rule 1 - no AZ warning)
    priv1 = ec2.create_subnet(VpcId=vpc_id, CidrBlock='10.0.1.0/24', AvailabilityZone='us-east-1a')['Subnet']
    priv2 = ec2.create_subnet(VpcId=vpc_id, CidrBlock='10.0.2.0/24', AvailabilityZone='us-east-1b')['Subnet']
    pub = ec2.create_subnet(VpcId=vpc_id, CidrBlock='10.0.3.0/24', AvailabilityZone='us-east-1a')['Subnet']

    igw = ec2.create_internet_gateway()['InternetGateway']
    ec2.attach_internet_gateway(InternetGatewayId=igw['InternetGatewayId'], VpcId=vpc_id)
    pub_rt = ec2.create_route_table(VpcId=vpc_id)['RouteTable']
    ec2.create_route(RouteTableId=pub_rt['RouteTableId'], DestinationCidrBlock='0.0.0.0/0', GatewayId=igw['InternetGatewayId'])
    ec2.associate_route_table(SubnetId=pub['SubnetId'], RouteTableId=pub_rt['RouteTableId'])

    # No EKS tags — only tag violation, nothing else
    tracker = SubnetTracker(vpc_id, 'us-east-1')
    tracker.fetch_data()
    recs = tracker.get_eks_recommendations()

    assert recs['status'] == 'Warning', f"Expected Warning, got {recs['status']}"
    assert any('kubernetes.io/role/internal-elb' in i for i in recs['issues'])
    assert any('kubernetes.io/role/elb' in i for i in recs['issues'])

@mock_aws
def test_subnet_details_total_ips_excludes_aws_reserved():
    """total_ips must be num_addresses - 5 (AWS reserved), and used + available must equal total."""
    ec2 = boto3.client('ec2', region_name='us-east-1')
    vpc = ec2.create_vpc(CidrBlock='10.0.0.0/16')['Vpc']
    ec2.create_subnet(VpcId=vpc['VpcId'], CidrBlock='10.0.1.0/24', AvailabilityZone='us-east-1a')

    tracker = SubnetTracker(vpc['VpcId'], 'us-east-1')
    tracker.fetch_data()
    details = tracker.get_subnet_details()

    assert len(details) == 1
    d = details[0]
    # /24 = 256 addresses, minus 5 AWS-reserved = 251 usable
    assert d['total_ips'] == 251
    # used + available must sum to total (no gap or overlap)
    assert d['used_ips'] + d['available_ips'] == d['total_ips']

@mock_aws
def test_subnet_tracker_logic():
    # Setup mock environment
    region = 'us-east-1'
    ec2 = boto3.client('ec2', region_name=region)

    # Create VPC
    vpc = ec2.create_vpc(CidrBlock='10.0.0.0/16')['Vpc']
    vpc_id = vpc['VpcId']

    # Create Subnets
    # 1. Public Subnet
    pub_sn = ec2.create_subnet(VpcId=vpc_id, CidrBlock='10.0.1.0/24', AvailabilityZone='us-east-1a')['Subnet']
    ec2.create_tags(Resources=[pub_sn['SubnetId']], Tags=[{'Key': 'Name', 'Value': 'PublicSubnet'}])

    # 2. Private Subnet
    priv_sn = ec2.create_subnet(VpcId=vpc_id, CidrBlock='10.0.2.0/24', AvailabilityZone='us-east-1b')['Subnet']
    ec2.create_tags(Resources=[priv_sn['SubnetId']], Tags=[{'Key': 'Name', 'Value': 'PrivateSubnet'}])

    # Setup Route Tables to make one public
    igw = ec2.create_internet_gateway()['InternetGateway']
    ec2.attach_internet_gateway(InternetGatewayId=igw['InternetGatewayId'], VpcId=vpc_id)

    pub_rt = ec2.create_route_table(VpcId=vpc_id)['RouteTable']
    ec2.create_route(RouteTableId=pub_rt['RouteTableId'], DestinationCidrBlock='0.0.0.0/0', GatewayId=igw['InternetGatewayId'])
    ec2.associate_route_table(SubnetId=pub_sn['SubnetId'], RouteTableId=pub_rt['RouteTableId'])

    # Run Tracker
    tracker = SubnetTracker(vpc_id, region)
    tracker.fetch_data()

    details = tracker.get_subnet_details()

    # Assertions
    assert len(details) == 2

    pub_detail = next(d for d in details if d['id'] == pub_sn['SubnetId'])
    assert pub_detail['type'] == 'Public'
    assert pub_detail['total_ips'] == 251

    priv_detail = next(d for d in details if d['id'] == priv_sn['SubnetId'])
    assert priv_detail['type'] == 'Private'

    # Check Unallocated Space
    unallocated = tracker.get_unallocated_space()
    # 10.0.0.0/16 minus 10.0.1.0/24 and 10.0.2.0/24
    # The math is complex to assert exactly but should not be empty
    assert len(unallocated) > 0

    # Check EKS Recommendations
    recommendations = tracker.get_eks_recommendations()
    # Should have warning because only 1 private subnet and missing tags
    assert recommendations['status'] == 'Warning'
    assert any("at least 2 private subnets" in issue for issue in recommendations['issues'])
    assert any("missing 'kubernetes.io/role/internal-elb'" in issue for issue in recommendations['issues'])

@mock_aws
def test_fetch_data_returns_all_subnets():
    """fetch_data must return all subnets across all pagination pages."""
    ec2 = boto3.client('ec2', region_name='us-east-1')
    vpc = ec2.create_vpc(CidrBlock='10.0.0.0/16')['Vpc']
    vpc_id = vpc['VpcId']

    for i in range(5):
        ec2.create_subnet(
            VpcId=vpc_id,
            CidrBlock=f'10.0.{i}.0/24',
            AvailabilityZone='us-east-1a',
        )

    tracker = SubnetTracker(vpc_id, 'us-east-1')
    tracker.fetch_data()

    assert len(tracker.subnets) == 5

@mock_aws
def test_get_subnet_details_returns_cached_object():
    """Repeated calls to get_subnet_details must return the same object, not recompute."""
    ec2 = boto3.client('ec2', region_name='us-east-1')
    vpc = ec2.create_vpc(CidrBlock='10.0.0.0/16')['Vpc']
    ec2.create_subnet(VpcId=vpc['VpcId'], CidrBlock='10.0.1.0/24', AvailabilityZone='us-east-1a')

    tracker = SubnetTracker(vpc['VpcId'], 'us-east-1')
    tracker.fetch_data()

    first = tracker.get_subnet_details()
    second = tracker.get_subnet_details()
    assert first is second  # identical object — not recomputed


@mock_aws
def test_cli_multi_vpc_does_not_require_vpc_id(tmp_path):
    """--multi-vpc should work without --vpc-id."""
    ec2 = boto3.client('ec2', region_name='us-east-1')
    vpc = ec2.create_vpc(CidrBlock='10.0.0.0/16')['Vpc']
    ec2.create_subnet(VpcId=vpc['VpcId'], CidrBlock='10.0.1.0/24', AvailabilityZone='us-east-1a')

    runner = CliRunner()
    result = runner.invoke(main, ['--multi-vpc', '--region', 'us-east-1', '--no-open', '--output-dir', str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / 'vpc-visualizer-multi.html').exists()


@mock_aws
def test_cli_multi_vpc_html_contains_subnet(tmp_path):
    """Multi-VPC visualization HTML must include actual subnet data."""
    ec2 = boto3.client('ec2', region_name='us-east-1')
    vpc = ec2.create_vpc(CidrBlock='10.0.0.0/16')['Vpc']
    sn = ec2.create_subnet(VpcId=vpc['VpcId'], CidrBlock='10.0.1.0/24', AvailabilityZone='us-east-1a')['Subnet']

    runner = CliRunner()
    result = runner.invoke(main, ['--multi-vpc', '--region', 'us-east-1', '--no-open', '--output-dir', str(tmp_path)])
    assert result.exit_code == 0, result.output

    html = (tmp_path / 'vpc-visualizer-multi.html').read_text()
    assert sn['SubnetId'] in html


@mock_aws
def test_cli_all_vpcs_report_no_vpc_id():
    """No --vpc-id should print tables for all VPCs and exit zero."""
    ec2 = boto3.client('ec2', region_name='us-east-1')
    vpc = ec2.create_vpc(CidrBlock='10.0.0.0/16')['Vpc']
    ec2.create_subnet(VpcId=vpc['VpcId'], CidrBlock='10.0.1.0/24', AvailabilityZone='us-east-1a')

    runner = CliRunner()
    result = runner.invoke(main, ['--region', 'us-east-1'])
    assert result.exit_code == 0, result.output
    assert vpc['VpcId'] in result.output


@mock_aws
def test_cli_all_vpcs_report_shows_all_vpcs():
    """No --vpc-id must print a section for every VPC in the region."""
    ec2 = boto3.client('ec2', region_name='us-east-1')
    vpc1 = ec2.create_vpc(CidrBlock='10.0.0.0/16')['Vpc']
    vpc2 = ec2.create_vpc(CidrBlock='10.1.0.0/16')['Vpc']
    ec2.create_subnet(VpcId=vpc1['VpcId'], CidrBlock='10.0.1.0/24', AvailabilityZone='us-east-1a')
    ec2.create_subnet(VpcId=vpc2['VpcId'], CidrBlock='10.1.1.0/24', AvailabilityZone='us-east-1b')

    runner = CliRunner()
    result = runner.invoke(main, ['--region', 'us-east-1'])
    assert result.exit_code == 0, result.output
    assert vpc1['VpcId'] in result.output
    assert vpc2['VpcId'] in result.output


@mock_aws
def test_fetch_data_raises_on_missing_vpc():
    """fetch_data must raise an error when the VPC ID does not exist."""
    tracker = SubnetTracker('vpc-00000000000000000', 'us-east-1')
    with pytest.raises(ValueError, match='vpc-00000000000000000'):
        tracker.fetch_data()


@mock_aws
def test_get_unallocated_space_returns_full_vpc_when_no_subnets():
    """With no subnets, the entire VPC CIDR should be reported as unallocated."""
    ec2 = boto3.client('ec2', region_name='us-east-1')
    vpc = ec2.create_vpc(CidrBlock='10.0.0.0/24')['Vpc']

    tracker = SubnetTracker(vpc['VpcId'], 'us-east-1')
    tracker.fetch_data()
    unallocated = tracker.get_unallocated_space()

    assert '10.0.0.0/24' in unallocated


@mock_aws
def test_get_unallocated_space_empty_when_fully_allocated():
    """With a subnet that covers the entire VPC CIDR, unallocated space should be empty."""
    ec2 = boto3.client('ec2', region_name='us-east-1')
    vpc = ec2.create_vpc(CidrBlock='10.0.1.0/24')['Vpc']
    ec2.create_subnet(VpcId=vpc['VpcId'], CidrBlock='10.0.1.0/24', AvailabilityZone='us-east-1a')

    tracker = SubnetTracker(vpc['VpcId'], 'us-east-1')
    tracker.fetch_data()
    unallocated = tracker.get_unallocated_space()

    assert unallocated == []
