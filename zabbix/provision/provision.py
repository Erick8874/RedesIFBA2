from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

API_URL = os.getenv("ZABBIX_API_URL", "http://172.20.99.11:8080/api_jsonrpc.php")
USERNAME = os.getenv("ZABBIX_USERNAME", "Admin")
PASSWORD = os.getenv("ZABBIX_PASSWORD", "zabbix")
SNMP_COMMUNITY = os.getenv("SNMP_COMMUNITY", "labpublic")
token: str | None = None
request_id = 0


def rpc(method: str, params: dict[str, Any]) -> Any:
    global request_id
    request_id += 1
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": request_id,
    }
    if token and method != "user.login":
        payload["auth"] = token
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json-rpc"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Zabbix API indisponível: {exc}") from exc
    if "error" in result:
        raise RuntimeError(f"Zabbix API {method}: {result['error']}")
    return result["result"]


def wait_for_api() -> None:
    last_error: Exception | None = None
    for _ in range(60):
        try:
            global token
            token = rpc(
                "user.login",
                {"username": USERNAME, "password": PASSWORD},
            )
            return
        except RuntimeError as exc:
            last_error = exc
            time.sleep(5)
    raise RuntimeError(f"Não foi possível autenticar no Zabbix: {last_error}")


def ensure_group(name: str) -> str:
    groups = rpc("hostgroup.get", {"filter": {"name": [name]}})
    if groups:
        return groups[0]["groupid"]
    result = rpc("hostgroup.create", {"name": name})
    return result["groupids"][0]


def get_template(candidates: list[str]) -> str | None:
    for name in candidates:
        result = rpc("template.get", {"filter": {"host": [name]}})
        if result:
            return result[0]["templateid"]
    return None


def ensure_host(
    name: str,
    group_id: str,
    address: str,
    *,
    snmp: bool = False,
    template_ids: list[str] | None = None,
    macros: list[dict[str, str]] | None = None,
) -> str:
    existing = rpc("host.get", {"filter": {"host": [name]}})
    if existing:
        return existing[0]["hostid"]
    interface: dict[str, Any] = {
        "type": 2 if snmp else 1,
        "main": 1,
        "useip": 1,
        "ip": address,
        "dns": "",
        "port": "161" if snmp else "10050",
    }
    if snmp:
        interface["details"] = {
            "version": 2,
            "community": "{$SNMP_COMMUNITY}",
        }
    params: dict[str, Any] = {
        "host": name,
        "name": name,
        "groups": [{"groupid": group_id}],
        "interfaces": [interface],
        "macros": macros or [{"macro": "{$SNMP_COMMUNITY}", "value": SNMP_COMMUNITY}],
    }
    if template_ids:
        params["templates"] = [{"templateid": template_id} for template_id in template_ids]
    return rpc("host.create", params)["hostids"][0]


def ensure_icmp_item_and_trigger(host_id: str, host_name: str) -> str:
    items = rpc(
        "item.get",
        {"hostids": [host_id], "filter": {"key_": ["icmpping"]}},
    )
    if items:
        item_id = items[0]["itemid"]
    else:
        item_id = rpc(
            "item.create",
            {
                "name": "ICMP ping",
                "key_": "icmpping",
                "hostid": host_id,
                "type": 3,
                "value_type": 3,
                "delay": "30s",
            },
        )["itemids"][0]
    triggers = rpc(
        "trigger.get",
        {"hostids": [host_id], "filter": {"description": [f"{host_name}: indisponível por ICMP"]}},
    )
    if triggers:
        return triggers[0]["triggerid"]
    return rpc(
        "trigger.create",
        {
            "description": f"{host_name}: indisponível por ICMP",
            "expression": f"max(/{host_name}/icmpping,3m)=0",
            "priority": 4,
        },
    )["triggerids"][0]


def ensure_agent_trigger(host_id: str, host_name: str) -> str:
    triggers = rpc(
        "trigger.get",
        {"hostids": [host_id], "filter": {"description": [f"{host_name}: agente indisponível"]}},
    )
    if triggers:
        return triggers[0]["triggerid"]
    return rpc(
        "trigger.create",
        {
            "description": f"{host_name}: agente indisponível",
            "expression": f"max(/{host_name}/agent.ping,3m)=0",
            "priority": 4,
        },
    )["triggerids"][0]


def ensure_web_scenario(host_id: str) -> None:
    existing = rpc(
        "httptest.get",
        {
            "hostids": [host_id],
            "filter": {"name": ["Jornada de compra - Café Planalto"]},
        },
    )
    if existing:
        return
    rpc(
        "httptest.create",
        {
            "name": "Jornada de compra - Café Planalto",
            "hostid": host_id,
            "delay": "1m",
            "retries": 1,
            "agent": "Zabbix",
            "steps": [
                {
                    "no": 1,
                    "name": "Abrir catálogo",
                    "url": "http://loja.cafeplanalto.lab/produtos",
                    "status_codes": "200",
                    "required": "Café Especial",
                    "timeout": "10s",
                },
                {
                    "no": 2,
                    "name": "Criar pedido",
                    "url": "http://loja.cafeplanalto.lab/pedidos",
                    "posts": '{"produto_id":1,"quantidade":1}',
                    "headers": [
                        {"name": "Content-Type", "value": "application/json"},
                    ],
                    "status_codes": "201",
                    "required": "pedido_id",
                    "timeout": "10s",
                },
            ],
        },
    )


def ensure_map(host_ids: dict[str, str]) -> None:
    name = "Café Planalto - topologia"
    if rpc("map.get", {"filter": {"name": [name]}}):
        return
    positions = {
        "r-matriz": (400, 150),
        "r-filial": (100, 150),
        "dns": (650, 50),
        "web": (650, 150),
        "api": (650, 250),
        "db": (850, 150),
        "cliente-carga": (100, 300),
        "sonda": (100, 400),
    }
    elements = []
    for index, (hostname, (x, y)) in enumerate(positions.items(), start=1):
        if hostname not in host_ids:
            continue
        elements.append(
            {
                "selementid": str(index),
                "elementtype": 0,
                "elements": [{"hostid": host_ids[hostname]}],
                "iconid_off": "1",
                "label": hostname,
                "x": x,
                "y": y,
            }
        )
    by_name = {item["label"]: item["selementid"] for item in elements}
    pairs = [
        ("r-filial", "r-matriz"),
        ("r-matriz", "dns"),
        ("r-matriz", "web"),
        ("r-matriz", "api"),
        ("r-matriz", "db"),
        ("r-filial", "cliente-carga"),
        ("r-filial", "sonda"),
    ]
    links = [
        {
            "selementid1": by_name[left],
            "selementid2": by_name[right],
            "drawtype": 0,
            "color": "00AA00",
            "label": "WAN" if {left, right} == {"r-filial", "r-matriz"} else "",
        }
        for left, right in pairs
        if left in by_name and right in by_name
    ]
    rpc(
        "map.create",
        {
            "name": name,
            "width": 1000,
            "height": 500,
            "label_type": 0,
            "grid_size": 50,
            "grid_show": 1,
            "grid_align": 1,
            "selements": elements,
            "links": links,
        },
    )


def ensure_telegram_action() -> None:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        print("Telegram do Zabbix não configurado; defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.")
        return

    media_name = "Café Planalto Telegram"
    media_types = rpc("mediatype.get", {"filter": {"name": [media_name]}})
    if media_types:
        media_type_id = media_types[0]["mediatypeid"]
    else:
        script = """
var params = JSON.parse(value);
var request = new HttpRequest();
request.addHeader('Content-Type: application/json');
var result = request.post(
    'https://api.telegram.org/bot' + params.token + '/sendMessage',
    JSON.stringify({
        chat_id: params.chat_id,
        text: params.subject + '\\n' + params.message
    })
);
if (request.getStatus() < 200 || request.getStatus() >= 300) {
    throw 'Telegram API returned HTTP ' + request.getStatus();
}
return result;
"""
        media_type_id = rpc(
            "mediatype.create",
            {
                "name": media_name,
                "type": 3,
                "parameters": [
                    {"name": "token", "value": bot_token},
                    {"name": "chat_id", "value": chat_id},
                    {"name": "subject", "value": "{ALERT.SUBJECT}"},
                    {"name": "message", "value": "{ALERT.MESSAGE}"},
                ],
                "script": script,
                "timeout": "10s",
                "process_tags": 1,
                "show_event_menu": 0,
                "event_menu_url": "",
                "event_menu_name": "",
                "message_templates": [],
            },
        )["mediatypeids"][0]

    users = rpc(
        "user.get",
        {
            "output": ["userid", "username"],
            "filter": {"username": [USERNAME]},
            "selectMedias": "extend",
        },
    )
    if not users:
        raise RuntimeError(f"Usuário Zabbix {USERNAME!r} não encontrado para notificação.")
    user = users[0]
    medias = user.get("medias", [])
    if not any(media.get("mediatypeid") == media_type_id for media in medias):
        medias.append(
            {
                "mediatypeid": media_type_id,
                "sendto": chat_id,
                "active": 0,
                "severity": 63,
                "period": "1-7,00:00-24:00",
            }
        )
        rpc("user.update", {"userid": user["userid"], "medias": medias})

    action_name = "Café Planalto - problemas de infraestrutura"
    if rpc("action.get", {"filter": {"name": [action_name]}}):
        return
    message_operation = {
        "operationtype": 0,
        "opmessage": {"default_msg": 1, "mediatypeid": media_type_id},
        "opmessage_usr": [{"userid": user["userid"]}],
    }
    rpc(
        "action.create",
        {
            "name": action_name,
            "eventsource": 0,
            "status": 0,
            "filter": {
                "evaltype": 0,
                "conditions": [
                    {
                        "conditiontype": 5,
                        "operator": 5,
                        "value": "3",
                    }
                ],
            },
            "operations": [message_operation],
            "recovery_operations": [message_operation],
        },
    )


def main() -> None:
    wait_for_api()
    group_id = ensure_group("Café Planalto")
    linux_template = get_template(["Linux by Zabbix agent"])
    snmp_template = get_template(["Generic by SNMP", "Network interfaces by SNMP"])
    nginx_template = get_template(["Nginx by HTTP"])
    postgres_template = get_template(["PostgreSQL by Zabbix agent 2"])
    if not linux_template:
        raise RuntimeError("Template oficial 'Linux by Zabbix agent' não encontrado.")
    if not snmp_template:
        raise RuntimeError("Template SNMP oficial com descoberta de interfaces não encontrado.")
    if not nginx_template:
        raise RuntimeError("Template oficial 'Nginx by HTTP' não encontrado.")
    if not postgres_template:
        raise RuntimeError("Template oficial 'PostgreSQL by Zabbix agent 2' não encontrado.")

    definitions = {
        "dns": ("172.20.10.10", False, [linux_template], []),
        "web": (
            "172.20.10.20",
            False,
            [linux_template, nginx_template],
            [
                {"macro": "{$NGINX.STUB_STATUS.HOST}", "value": "127.0.0.1"},
                {"macro": "{$NGINX.STUB_STATUS.PATH}", "value": "/nginx_status"},
                {"macro": "{$NGINX.STUB_STATUS.PORT}", "value": "80"},
            ],
        ),
        "api": ("172.20.10.21", False, [linux_template], []),
        "db": (
            "172.20.10.22",
            False,
            [linux_template, postgres_template],
            [
                {"macro": "{$PG.URI}", "value": "tcp://127.0.0.1:5432"},
                {"macro": "{$PG.USER}", "value": "cafe"},
                {"macro": "{$PG.PASSWORD}", "value": os.getenv("POSTGRES_PASSWORD", "cafeplanalto-local")},
                {"macro": "{$PG.DATABASE}", "value": "cafeplanalto"},
            ],
        ),
        "cliente-carga": ("172.20.20.20", False, [linux_template], []),
        "sonda": ("172.20.20.30", False, [linux_template], []),
        "r-matriz": ("172.20.99.1", True, [snmp_template], []),
        "r-filial": ("10.0.0.2", True, [snmp_template], []),
    }
    host_ids: dict[str, str] = {}
    for name, (address, snmp, templates, macros) in definitions.items():
        host_ids[name] = ensure_host(
            name,
            group_id,
            address,
            snmp=snmp,
            template_ids=templates,
            macros=macros or [{"macro": "{$SNMP_COMMUNITY}", "value": SNMP_COMMUNITY}],
        )

    router_triggers = {
        name: ensure_icmp_item_and_trigger(host_ids[name], name)
        for name in ("r-filial", "r-matriz")
    }
    branch_dependencies = []
    for name in ("cliente-carga", "sonda"):
        trigger_id = ensure_agent_trigger(host_ids[name], name)
        branch_dependencies.append(trigger_id)
    for trigger_id in branch_dependencies:
        rpc(
            "trigger.update",
            {
                "triggerid": trigger_id,
                "dependencies": [{"triggerid": router_triggers["r-filial"]}],
            },
        )

    ensure_web_scenario(host_ids["web"])
    ensure_map(host_ids)
    ensure_telegram_action()
    print("Provisionamento do Zabbix concluído: hosts, templates, triggers, cenário web e mapa.")


if __name__ == "__main__":
    main()
