"""Tests for the visualizer module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from moto import mock_aws
import boto3

from subnet_tracker.visualizer import (
    _subnet_to_dict,
    _vpc_cidr_range,
    _subnet_position,
    _build_vpc_data,
    _render_html,
    generate_visualization,
    generate_multi_vpc_visualization,
    open_visualization,
)


@mock_aws
def test_subnet_to_dict():
    subnet = {
        "SubnetId": "subnet-123",
        "CidrBlock": "10.0.1.0/24",
        "AvailabilityZone": "us-east-1a",
        "Tags": [{"Key": "Name", "Value": "PublicSubnet"}],
    }
    result = _subnet_to_dict(subnet)
    assert result["id"] == "subnet-123"
    assert result["name"] == "PublicSubnet"
    assert result["cidr"] == "10.0.1.0/24"
    assert result["az"] == "us-east-1a"
    assert result["type"] == "Private"


@mock_aws
def test_subnet_to_dict_with_type():
    subnet = {
        "SubnetId": "subnet-123",
        "CidrBlock": "10.0.1.0/24",
        "AvailabilityZone": "us-east-1a",
        "Tags": [{"Key": "Name", "Value": "PublicSubnet"}],
        "_type": "Public",
    }
    result = _subnet_to_dict(subnet)
    assert result["type"] == "Public"


@mock_aws
def test_subnet_to_dict_no_name_tag():
    subnet = {
        "SubnetId": "subnet-123",
        "CidrBlock": "10.0.1.0/24",
        "AvailabilityZone": "us-east-1a",
        "Tags": [],
    }
    result = _subnet_to_dict(subnet)
    assert result["name"] == "N/A"


def test_vpc_cidr_range():
    cidrs = ["10.0.0.0/16", "10.0.1.0/24"]
    start, end = _vpc_cidr_range(cidrs)
    assert start == 167772160  # 10.0.0.0
    assert end == 167837695    # 10.0.255.255


def test_subnet_position():
    pos = _subnet_position("10.0.1.0/24", 167772160, 167778695)
    assert pos["x"] > 0
    assert pos["width"] > 0
    assert pos["x"] + pos["width"] <= 100


def test_build_vpc_data():
    vpc_id = "vpc-123"
    subnets = [
        {
            "SubnetId": "subnet-1",
            "CidrBlock": "10.0.1.0/24",
            "AvailabilityZone": "us-east-1a",
            "Tags": [{"Key": "Name", "Value": "Public"}],
            "AvailableIpAddressCount": 251,
            "_type": "Public",
        }
    ]
    result = _build_vpc_data(vpc_id, subnets)
    assert result["id"] == vpc_id
    assert len(result["subnets"]) == 1
    assert result["subnets"][0]["name"] == "Public"


def test_build_vpc_data_empty_cidrs():
    vpc_id = "vpc-123"
    result = _build_vpc_data(vpc_id, [])
    assert result["cidrs"] == ["10.0.0.0/16"]


def test_render_html_contains_js():
    vpcs = [{
        "id": "vpc-123",
        "cidrs": ["10.0.0.0/16"],
        "vpc_start": 167772160,
        "vpc_end": 167778695,
        "subnets": [{
            "id": "subnet-1",
            "name": "Public",
            "cidr": "10.0.1.0/24",
            "az": "us-east-1a",
            "type": "Public",
            "x": 0.39,
            "width": 3.91,
            "total_ips": 256,
            "available": 251,
            "tags": [],
        }],
    }]
    html = _render_html(vpcs)
    assert "<script>" in html
    assert "const data" in html
    assert "vpc-123" in html


def test_render_html_contains_css():
    html = _render_html([{"id": "vpc-1", "cidrs": ["10.0.0.0/16"], "vpc_start": 0, "vpc_end": 1, "subnets": []}])
    assert "<style>" in html
    assert "--bg:" in html
    assert "subnet-bar" in html


def test_render_html_multi_vpc():
    vpcs = [
        {"id": "vpc-1", "cidrs": ["10.0.0.0/16"], "vpc_start": 0, "vpc_end": 1, "subnets": []},
        {"id": "vpc-2", "cidrs": ["172.16.0.0/16"], "vpc_start": 0, "vpc_end": 1, "subnets": []},
    ]
    html = _render_html(vpcs)
    assert "vpc-1" in html
    assert "vpc-2" in html


@mock_aws
def test_generate_visualization(tmp_path):
    ec2 = boto3.client("ec2", region_name="us-east-1")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]
    subnet = ec2.create_subnet(
        VpcId=vpc["VpcId"],
        CidrBlock="10.0.1.0/24",
        AvailabilityZone="us-east-1a",
    )["Subnet"]
    ec2.create_tags(Resources=[subnet["SubnetId"]], Tags=[{"Key": "Name", "Value": "Test"}])

    # Re-fetch subnet to get the tags
    subnets = ec2.describe_subnets(SubnetIds=[subnet["SubnetId"]])["Subnets"]

    filepath = generate_visualization(
        vpc_data=vpc,
        subnets=subnets,
        vpc_id=vpc["VpcId"],
        output_dir=str(tmp_path),
    )

    assert filepath.exists()
    content = filepath.read_text()
    assert "vpc-visualizer-" in str(filepath)
    assert "Test" in content


@mock_aws
def test_generate_multi_vpc_visualization(tmp_path):
    ec2 = boto3.client("ec2", region_name="us-east-1")
    vpc1 = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]
    vpc2 = ec2.create_vpc(CidrBlock="172.16.0.0/16")["Vpc"]

    filepath = generate_multi_vpc_visualization(
        vpcs_data=[vpc1, vpc2],
        output_dir=str(tmp_path),
    )

    assert filepath.exists()
    assert "vpc-visualizer-multi" in str(filepath)


@mock_aws
def test_generate_visualization_opens_in_browser(tmp_path):
    ec2 = boto3.client("ec2", region_name="us-east-1")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]
    subnet = ec2.create_subnet(
        VpcId=vpc["VpcId"],
        CidrBlock="10.0.1.0/24",
        AvailabilityZone="us-east-1a",
    )["Subnet"]

    with patch("subnet_tracker.visualizer.webbrowser.open") as mock_open:
        filepath = generate_visualization(
            vpc_data=vpc,
            subnets=[subnet],
            vpc_id=vpc["VpcId"],
            output_dir=str(tmp_path),
        )
        open_visualization(filepath)
        mock_open.assert_called_once()
        assert filepath.as_uri() in mock_open.call_args[0]
