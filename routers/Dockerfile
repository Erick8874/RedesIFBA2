FROM alpine:3.21
RUN apk add --no-cache iproute2 iptables net-snmp-tools net-snmp
COPY router-init.sh /usr/local/bin/router-init
COPY snmpd.conf /etc/snmp/snmpd.conf
RUN chmod 0755 /usr/local/bin/router-init
EXPOSE 161/udp
CMD ["/usr/local/bin/router-init"]
