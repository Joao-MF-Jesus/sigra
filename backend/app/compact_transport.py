"""Lossless, opt-in transport only. No metric, persistence or evidence projection.

Every original container becomes a typed node; values referring to containers
are {"r": index}. Original objects having a literal r key are nodes themselves,
so they cannot collide with references. Dictionary entries are interned only
when their ordered members/values are exactly equal. The expanded JSON model
is unchanged; this is not gzip and does not rely on Content-Encoding.
"""
import json
import os

from fastapi.encoders import jsonable_encoder

VERSION = "sigra-json-dictionary-v1"
HEADER = b"x-sigra-transport"
MAX_WIRE_BYTES = 4_000_000  # margin below the documented 4.5 MB Function cap


def json_bytes(value):
    return json.dumps(value,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode("utf-8")


def pack(value):
    nodes=[]
    known={}
    def encode(item,depth=0):
        if depth > 100:
            raise ValueError("TRANSPORT_DEPTH_EXCEEDED")
        if isinstance(item,dict):
            node=["o",[[str(key),encode(child,depth+1)] for key,child in item.items()]]
        elif isinstance(item,list):
            node=["a",[encode(child,depth+1) for child in item]]
        else:
            return item
        key=json_bytes(node)
        index=known.get(key)
        if index is None:
            index=len(nodes)
            known[key]=index
            nodes.append(node)
        return {"r":index}
    normalized=jsonable_encoder(value)
    root=encode(normalized)
    return {"transport":VERSION,"root":root,"nodes":nodes}


def unpack(value):
    if not isinstance(value,dict) or value.get("transport") != VERSION:
        return value
    if set(value) != {"transport","root","nodes"} or not isinstance(value["nodes"],list):
        raise ValueError("TRANSPORT_INVALID")
    nodes=value["nodes"]
    visits=0
    def decode(item,depth=0):
        nonlocal visits
        visits+=1
        if depth>100 or visits>5_000_000:
            raise ValueError("TRANSPORT_EXPANSION_LIMIT")
        if not isinstance(item,dict):
            if isinstance(item,list):
                raise ValueError("TRANSPORT_INVALID_VALUE")
            return item
        if set(item)!={"r"} or type(item["r"]) is not int or not 0<=item["r"]<len(nodes):
            raise ValueError("TRANSPORT_INVALID_REFERENCE")
        node=nodes[item["r"]]
        if not isinstance(node,list) or len(node)!=2:
            raise ValueError("TRANSPORT_INVALID_NODE")
        if node[0]=="a" and isinstance(node[1],list):
            return [decode(child,depth+1) for child in node[1]]
        if node[0]=="o" and isinstance(node[1],list):
            result={}
            for pair in node[1]:
                if not isinstance(pair,list) or len(pair)!=2 or not isinstance(pair[0],str) or pair[0] in result:
                    raise ValueError("TRANSPORT_INVALID_MEMBER")
                result[pair[0]]=decode(pair[1],depth+1)
            return result
        raise ValueError("TRANSPORT_INVALID_NODE")
    return decode(value["root"])


class CompactJSONMiddleware:
    """After existing authorization, serialize ONLY opted-in JSON responses.

    Does not parse request bodies/cookies, cache data across users, change the
    stored result or touch CSV streams. Original response headers/status remain.
    Small responses and non-opt-in clients retain the existing contract.
    """
    def __init__(self,app):
        self.app=app

    async def __call__(self,scope,receive,send):
        if scope["type"]!="http" or dict(scope.get("headers",[])).get(HEADER)!=VERSION.encode():
            return await self.app(scope,receive,send)
        start=None
        chunks=[]
        async def intercept(message):
            nonlocal start
            if message["type"]=="http.response.start":
                headers=dict(message.get("headers",[]))
                if not headers.get(b"content-type",b"").startswith(b"application/json") or message["status"]>=400:
                    await send(message)
                    start=False
                else:
                    start=message
                return
            if message["type"]!="http.response.body" or start is False:
                return await send(message)
            chunks.append(message.get("body",b""))
            if message.get("more_body",False):
                return
            body=b"".join(chunks)
            if len(body)>=65536:
                packed=json_bytes(pack(json.loads(body)))
                # Structural dictionary need not help every input; never replace
                # a smaller original body with a larger representation.
                if len(packed)<len(body):
                    body=packed
            if len(body) > MAX_WIRE_BYTES and os.environ.get("SIGRA_VERCEL_ENABLED") == "true":
                # Never truncate or ask the user to blindly resubmit a POST that
                # may already have been saved. Include only the saved receipt.
                original=json.loads(b"".join(chunks))
                body=json_bytes({"detail": {"code":"response_transport_limit", "message":"Resposta excede o transporte preparado. Consulte Meus testes antes de repetir a operação."},
                                 "test_run": original.get("test_run") if isinstance(original,dict) else None})
                start={**start,"status":503}
            headers=[(k,v) for k,v in start.get("headers",[]) if k.lower()!=b"content-length"]
            headers.append((b"content-length",str(len(body)).encode()))
            headers.append((b"vary",b"X-SIGRA-Transport"))
            if not any(k.lower()==b"cache-control" for k,_ in headers):
                headers.append((b"cache-control",b"no-store"))
            start={**start,"headers":headers}
            await send(start)
            await send({"type":"http.response.body","body":body,"more_body":False})
        await self.app(scope,receive,intercept)
