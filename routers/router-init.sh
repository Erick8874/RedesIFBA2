#!/bin/sh
set -eu

iptables -P FORWARD ACCEPT
if ! iptables -C FORWARD -o eth0 -d 172.20.0.0/16 -j DROP; then
  iptables -A FORWARD -o eth0 -d 172.20.0.0/16 -j DROP
fi

configure_wan_address() {
  docker_address="$1"
  router_address="$2"
  if ip -o -4 addr show dev eth1 | grep -Fq "inet $docker_address"; then
    ip addr del "$docker_address" dev eth1
  fi
  ip addr replace "$router_address" dev eth1
}

community="${SNMP_COMMUNITY:-labpublic}"
case "$community" in
  *[!A-Za-z0-9_-]*|'')
    echo "SNMP_COMMUNITY deve conter apenas letras, números, _ ou -" >&2
    exit 2
    ;;
esac
sed -i "s/@SNMP_COMMUNITY@/$community/" /etc/snmp/snmpd.conf

case "${ROUTER_NAME:?ROUTER_NAME precisa ser definido}" in
  r-matriz)
    configure_wan_address 10.0.0.1/29 10.0.0.1/30
    ip route replace prohibit 172.20.20.0/24 metric 32760
    ip route replace 172.20.20.0/24 via 10.0.0.2 metric 100
    ;;
  r-filial)
    configure_wan_address 10.0.0.2/29 10.0.0.2/30
    ip route replace prohibit 172.20.10.0/24 metric 32760
    ip route replace prohibit 172.20.99.0/24 metric 32760
    ip route replace 172.20.10.0/24 via 10.0.0.1 metric 100
    ip route replace 172.20.99.0/24 via 10.0.0.1 metric 100
    ;;
  *)
    echo "Roteador não reconhecido: ${ROUTER_NAME}" >&2
    exit 2
    ;;
esac

exec snmpd -f -Lo -C -c /etc/snmp/snmpd.conf
