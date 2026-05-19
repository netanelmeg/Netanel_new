const NODE_DATA = {
  'hub-vnet': {
    tag: 'CONTAINER',
    title: 'Hub VNet',
    description: 'The central VNet in a hub-and-spoke topology. Holds shared plumbing: VPN Gateway, Azure Firewall, BGP, DNS resolvers. Workloads don\'t live here — only infrastructure.',
    bullets: [
      'Address space: <code>10.0.0.0/16</code> (example)',
      'Every spoke peers <em>only</em> with the hub — never directly with other spokes',
      'Contains the device that inspects inter-spoke traffic (the firewall)',
    ],
    gotcha: 'Common mistake: putting workloads in the hub. Keep it for plumbing only — easier to manage, secure, and audit.',
  },
  'firewall': {
    tag: 'NETWORK DEVICE',
    title: 'Azure Firewall',
    description: 'A managed, stateful firewall service that lives in the hub. Inspects, allows, and denies traffic between spokes, between Azure and on-prem, and to/from the internet.',
    bullets: [
      'Has a private IP (e.g., <code>10.0.1.4</code>) used as the "next hop" in spoke route tables',
      'Replaces or complements an NVA (Network Virtual Appliance like Fortinet/Palo Alto VM)',
      'Supports application rules (FQDN-based), network rules (IP/port), and NAT rules',
    ],
    tip: 'The firewall is what makes hub-and-spoke actually work. Without something to forward traffic between spokes, peering non-transitivity would block them entirely.',
  },
  'vpn-gw': {
    tag: 'AZURE RESOURCE',
    title: 'VPN Gateway',
    description: 'Builds and terminates the encrypted Site-to-Site VPN tunnel between Azure and your on-prem network. Always lives in a special subnet called <code>GatewaySubnet</code>.',
    bullets: [
      'Speaks IKE/IPsec to establish the encrypted tunnel',
      'Can speak BGP to dynamically exchange routes with on-prem',
      'Has its own Azure-assigned public IP (doesn\'t change unless you recreate it)',
    ],
    gotcha: 'Don\'t confuse this with the Local Network Gateway. VPN Gateway = Azure side. LNG = Azure\'s description of the on-prem side.',
  },
  'bgp': {
    tag: 'PROTOCOL',
    title: 'BGP — Border Gateway Protocol',
    description: 'The protocol that lets the VPN Gateway and on-prem router automatically exchange routing information. The same protocol that runs the public internet.',
    bullets: [
      'Replaces the manual list of address ranges on the LNG',
      'When on-prem adds a new subnet, BGP advertises it to Azure automatically',
      'Required for route-based VPN; not available with policy-based VPN',
    ],
    tip: 'Without BGP, every new on-prem subnet means manually updating the LNG. With BGP, it\'s automatic. Always enable BGP in modern enterprise setups.',
  },
  'lng': {
    tag: 'AZURE RESOURCE',
    title: 'Local Network Gateway',
    description: 'Azure\'s representation of your on-prem side. It\'s an Azure resource that <em>describes</em> on-prem — not something that lives on-prem.',
    bullets: [
      'Stores the on-prem public IP (the IP your firewall presents to the internet)',
      'Stores the list of on-prem private subnets (when not using BGP)',
      'Stores the BGP peer IP (when BGP is enabled)',
    ],
    gotcha: 'When on-prem IP changes → update the LNG, not the VPN Gateway. Easy to confuse because of the name.',
  },
  'on-prem': {
    tag: 'EXTERNAL',
    title: 'On-Premises Network',
    description: 'Your physical office or datacenter. Contains servers, switches, a firewall/router that terminates the VPN tunnel, and a DNS server.',
    bullets: [
      'Address space: <code>192.168.0.0/16</code> (example — usually RFC1918 private space)',
      'Connects to Azure via Site-to-Site VPN (over the internet) or ExpressRoute (private fiber)',
      'Has its own DNS server that resolves on-prem-specific names like <code>*.corp.local</code>',
    ],
  },
  'onprem-router': {
    tag: 'PHYSICAL DEVICE',
    title: 'On-Prem Router / Firewall',
    description: 'The physical device (or virtual appliance) at your office/datacenter that terminates the VPN tunnel and acts as the BGP peer with Azure.',
    bullets: [
      'Common vendors: Cisco, Fortinet, Palo Alto, Juniper',
      'Has a public IP (this is what the Azure LNG points at)',
      'Configured with IKE/IPsec settings matching the Azure VPN Gateway',
    ],
    gotcha: 'A common failure mode: mismatched IKE phase 1/2 settings between Azure and on-prem. Always document and version-control both sides\' settings.',
  },
  'onprem-dns': {
    tag: 'PHYSICAL/VIRTUAL SERVER',
    title: 'On-Prem DNS Server',
    description: 'A DNS server (often Windows Server DNS, BIND, or a managed appliance) that owns your private namespace like <code>*.corp.local</code>.',
    bullets: [
      'Has a private IP reachable through the tunnel (e.g., <code>192.168.1.10</code>)',
      'Configured with conditional forwarders so it knows where to send Azure-specific queries',
      'Azure DNS forwards <code>*.corp.local</code> queries to this server',
    ],
    tip: 'The classic ticket: "Ping by IP works, ping by name fails." 90% of the time it\'s a missing or misconfigured conditional forwarder.',
  },
  'spoke-a': {
    tag: 'SPOKE VNET',
    title: 'Spoke-A (Production)',
    description: 'A spoke VNet that holds production workloads. Peered only with the hub VNet. Cannot reach Spoke-B directly because peering is non-transitive.',
    bullets: [
      'Address space: <code>10.1.0.0/16</code>',
      'Route table forces all non-local traffic through the hub firewall',
      'Links to the shared Private DNS Zone for name resolution',
    ],
    tip: 'The mini-card inside this spoke shows the actual route table entry that makes inter-spoke traffic work. Read it like the Azure portal would display it.',
  },
  'spoke-b': {
    tag: 'SPOKE VNET',
    title: 'Spoke-B (Development)',
    description: 'A spoke VNet that holds dev/test workloads. Identical pattern to Spoke-A — peered only with the hub, routes traffic through the firewall.',
    bullets: [
      'Address space: <code>10.2.0.0/16</code>',
      'Address space must NOT overlap with any other spoke or with on-prem',
      'In real environments, you might have 10+ spokes following this exact pattern',
    ],
    gotcha: 'Overlapping address spaces is the #1 cause of "peering created but traffic doesn\'t flow." Always plan your address ranges centrally before creating VNets.',
  },
  'dns-zone': {
    tag: 'AZURE RESOURCE',
    title: 'Private DNS Zone',
    description: 'A standalone Azure resource that hosts a private namespace (e.g., <code>corp.local</code>, <code>privatelink.database.windows.net</code>). VNets <em>link</em> to it to gain name resolution.',
    bullets: [
      'One zone can be linked to many VNets — that\'s its superpower',
      'Doesn\'t "live inside" any VNet — completely independent resource',
      'For hybrid name resolution, pair with conditional forwarders to on-prem DNS',
    ],
    tip: 'Modern alternative: Azure DNS Private Resolver — a managed service that handles the forwarding logic for you. Worth knowing for new deployments.',
  },
};
