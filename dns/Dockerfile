FROM coredns/coredns:1.12.0
COPY Corefile /etc/coredns/Corefile
COPY cafeplanalto.lab.zone /etc/coredns/cafeplanalto.lab.zone
ENTRYPOINT ["/coredns"]
CMD ["-conf", "/etc/coredns/Corefile"]
