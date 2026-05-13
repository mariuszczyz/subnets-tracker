import boto3
import ipaddress
from typing import List, Dict, Any

class SubnetTracker:
    def __init__(self, vpc_id: str, region: str):
        self.vpc_id = vpc_id
        self.region = region
        self.ec2 = boto3.client('ec2', region_name=region)
        self.vpc_data = {}
        self.subnets = []
        self.route_tables = []
        self._subnet_details_cache = None

    def fetch_data(self):
        """Fetches all necessary data from AWS."""
        # Fetch VPC details
        vpcs = self.ec2.describe_vpcs(VpcIds=[self.vpc_id])['Vpcs']
        if not vpcs:
            raise ValueError(f"VPC {self.vpc_id} not found.")
        self.vpc_data = vpcs[0]

        # Fetch Subnets
        subnet_paginator = self.ec2.get_paginator('describe_subnets')
        self.subnets = [
            sn
            for page in subnet_paginator.paginate(Filters=[{'Name': 'vpc-id', 'Values': [self.vpc_id]}])
            for sn in page['Subnets']
        ]

        # Fetch Route Tables
        rt_paginator = self.ec2.get_paginator('describe_route_tables')
        self.route_tables = [
            rt
            for page in rt_paginator.paginate(Filters=[{'Name': 'vpc-id', 'Values': [self.vpc_id]}])
            for rt in page['RouteTables']
        ]
        self._subnet_details_cache = None

    def is_public(self, subnet_id: str) -> bool:
        """
        Determines if a subnet is public by checking if its route table
        has a route to an Internet Gateway (igw-).
        """
        # Find the route table for this subnet
        rtb = next((rt for rt in self.route_tables if any(assoc.get('SubnetId') == subnet_id for assoc in rt.get('Associations', []))), None)
        
        # If no explicit association, find the main route table
        if not rtb:
            rtb = next((rt for rt in self.route_tables if any(assoc.get('Main') for assoc in rt.get('Associations', []))), None)

        if not rtb:
            return False

        for route in rtb.get('Routes', []):
            gateway_id = route.get('GatewayId', '')
            if gateway_id.startswith('igw-'):
                return True
        return False

    def get_subnet_details(self) -> List[Dict[str, Any]]:
        """Processes and returns detailed information for each subnet."""
        if self._subnet_details_cache is not None:
            return self._subnet_details_cache
        details = []
        for sn in self.subnets:
            cidr = sn['CidrBlock']
            net = ipaddress.ip_network(cidr)

            # AWS reserves 5 IPs in each subnet
            total_ips = net.num_addresses - 5
            available_ips = sn['AvailableIpAddressCount']
            used_ips = total_ips - available_ips

            # Get Name tag
            name = next((tag['Value'] for tag in sn.get('Tags', []) if tag['Key'] == 'Name'), 'N/A')

            # EKS Tags
            eks_internal_elb = any(tag['Key'] == 'kubernetes.io/role/internal-elb' for tag in sn.get('Tags', []))
            eks_elb = any(tag['Key'] == 'kubernetes.io/role/elb' for tag in sn.get('Tags', []))

            details.append({
                'id': sn['SubnetId'],
                'name': name,
                'az': sn['AvailabilityZone'],
                'cidr': cidr,
                'type': 'Public' if self.is_public(sn['SubnetId']) else 'Private',
                'total_ips': total_ips,
                'used_ips': used_ips,
                'available_ips': available_ips,
                'eks_internal_elb': eks_internal_elb,
                'eks_elb': eks_elb
            })
        self._subnet_details_cache = details
        return details

    def get_unallocated_space(self) -> List[str]:
        """Calculates unallocated CIDR blocks within the VPC."""
        vpc_cidrs = [assoc['CidrBlock'] for assoc in self.vpc_data.get('CidrBlockAssociationSet', [])]
        if not vpc_cidrs:
            vpc_cidrs = [self.vpc_data['CidrBlock']]

        allocated_cidrs = [sn['CidrBlock'] for sn in self.subnets]
        unallocated = []

        for vpc_cidr in vpc_cidrs:
            vpc_net = ipaddress.ip_network(vpc_cidr)
            remaining = [vpc_net]
            
            for alloc_cidr in allocated_cidrs:
                alloc_net = ipaddress.ip_network(alloc_cidr)
                new_remaining = []
                for rem_net in remaining:
                    if alloc_net.overlaps(rem_net):
                        # This is a bit complex with ipaddress, usually requires iterating or using a library
                        # For simplicity, we can use address_exclude if alloc_net is a subset
                        try:
                            new_remaining.extend(list(rem_net.address_exclude(alloc_net)))
                        except ValueError:
                            # If alloc_net is not a subnet of rem_net, it might be the other way or partial
                            # In VPCs, subnets must be subsets of VPC CIDRs.
                            new_remaining.append(rem_net)
                    else:
                        new_remaining.append(rem_net)
                remaining = new_remaining
            unallocated.extend([str(net) for net in remaining])
        
        return unallocated

    def get_eks_recommendations(self) -> Dict[str, Any]:
        """Evaluates subnets for EKS best practices."""
        details = self.get_subnet_details()
        private_subnets = [d for d in details if d['type'] == 'Private']
        public_subnets = [d for d in details if d['type'] == 'Public']
        
        recommendations = {
            'status': 'OK',
            'issues': [],
            'proposals': []
        }

        # Rule 1: At least 2 private subnets in different AZs
        private_azs = set(d['az'] for d in private_subnets)
        if len(private_azs) < 2:
            recommendations['status'] = 'Warning'
            recommendations['issues'].append("EKS recommends at least 2 private subnets in different Availability Zones.")

        # Rule 2: Sufficient IPs (EKS recommends at least /28, but ideally more for pods)
        for sn in private_subnets:
            if sn['available_ips'] < 16:
                recommendations['status'] = 'Warning'
                recommendations['issues'].append(f"Subnet {sn['id']} has very few available IPs ({sn['available_ips']}), which may restrict EKS scaling.")

        # Rule 3: Tags for Load Balancers
        missing_internal_tags = [sn['id'] for sn in private_subnets if not sn['eks_internal_elb']]
        if missing_internal_tags:
            recommendations['status'] = 'Warning'
            recommendations['issues'].append(f"Private subnets missing 'kubernetes.io/role/internal-elb' tag: {', '.join(missing_internal_tags)}")

        missing_elb_tags = [sn['id'] for sn in public_subnets if not sn['eks_elb']]
        if missing_elb_tags:
            recommendations['status'] = 'Warning'
            recommendations['issues'].append(f"Public subnets missing 'kubernetes.io/role/elb' tag: {', '.join(missing_elb_tags)}")

        # Proposals for new subnets
        unallocated = self.get_unallocated_space()
        if not private_subnets and unallocated:
            recommendations['proposals'].append("Consider creating at least 2 private subnets from unallocated space for EKS nodes.")

        return recommendations
