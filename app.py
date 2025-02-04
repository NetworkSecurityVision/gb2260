from sanic import Sanic
from sanic.log import logger
from sanic.response import json, text
from sanic import Blueprint
import sqlite3
from json import load as jsonload
import os
from copy import deepcopy
import time

app = Sanic(__name__)

app.static("/static", "./static")


class DataSource:
    def init(self):
        self.conn2020 = sqlite3.connect("./data/2020/fuzzy.db")
        self.cursor2020 = self.conn2020
        with open("./data/2020/data.json") as f:
            self.data2020 = jsonload(f)

    def close(self):
        self.conn2020.close()

    def _fullpath(self, code):
        if code == "0":
            return "中国"

        def g(code):
            return self.data2020[code]["name"]

        cl = len(code)
        path = []

        if cl >= 2:
            path.append(g(code[:2]))
        if cl >= 4:
            n = g(code[:4])
            if n != path[-1]:
                path.append(n)
        if cl >= 6:
            n = g(code[:6])
            if n != path[-1]:
                path.append(n)
        if cl > 6:
            n = g(code)
            if n != path[-1]:
                path.append(n)

        return " ".join(path)

    def _get_children(self, code):
        children = self.data2020[code].get("children")
        if children is None:
            return []

        r = []
        for code in children:
            child = self.data2020[code]
            if child.get("is_direct"):
                r.extend(self._get_children(code))
            else:
                r.append({"code": code, "name": child["name"]})
        return r

    def areas(self, code, with_children, with_location):

        r = {"code": code}

        a = self.data2020.get(code)
        if a is None:
            return {"err": "code: %s is not exist" % code}

        r["name"] = a["name"]

        if with_location and a.get("location"):
            r["location"] = {
                "latitude": a["location"]["lat"],
                "longitude": a["location"]["lng"],
                "type": a["location"]["type"],
            }
        r["fullpath"] = self._fullpath(code)

        if with_children:
            r["children"] = self._get_children(code)

        return r

    def fuzzy(self, k, count=6, with_pinyin=False):
        if k.isnumeric():
            rows = self.cursor2020.execute(
                'select code, pinyin from divisions where code match "*%s*" limit %s'
                % (k, count)
            )
        else:
            # SQL 转义
            k = k.replace("'", "")
            rows = self.cursor2020.execute(
                'select code, pinyin from divisions where divisions match "%s" limit %s'
                % (list(k.replace(" ", "")), count)
            )

        def f_fill(row):
            code = row[0]
            pinyin = row[1]
            r = {
                "code": code,
                "name": self.data2020[code]["name"],
                "fullpath": self._fullpath(code),
            }
            if with_pinyin:
                r["pinyin"] = "".join(pinyin.split(" "))
            return r

        return list(map(f_fill, rows.fetchall()))


@app.route("/status")
async def status(request):
    return text("ok")


bp = Blueprint("division", url_prefix="/china/division/<year:2020>")


@bp.listener("before_server_start")
async def setup_connection(app, loop):
    global Source
    Source = DataSource()
    Source.init()


@bp.listener("after_server_stop")
async def close_connection(app, loop):
    Source.close()
    logger.info("server stopped")


@bp.route("/fuzzy")
async def fuzzy(request, year):
    start = time.time()
    k = request.args.get("k")
    with_pinyin = request.args.get("pinyin") == "true"
    size = request.args.get("size")

    if not k:
        return json({"err": "parameter k must signed"})

    if size is None:
        size = 5
    elif size.isnumeric():
        size = int(size)
    else:
        return json({"err": "parameter size must be number or empty"})

    r = Source.fuzzy(k, with_pinyin=with_pinyin, count=size)
    return json(r, headers={"X-Time-Used": time.time() - start})


@bp.route("/<code:[0-9]+>")
async def areas(request, year, code):
    """
    response type
    {
        code: '11',
        name: "北京市",
        fullpath: "北京市",
        GCJ02: {
            latitude: 116.405285,
            longitude: 39.904989,
        }
        children: [
            {
                code: 1101,
                name: "北京市"
            }, ...
        ]
    }
    """

    def args_equal(p, v):
        return request.args.get(p) and request.args.get(p) == v

    with_children = args_equal("children", "true")
    with_location = args_equal("location", "true")

    return json(Source.areas(code, with_children, with_location))


app.blueprint(bp)

port = os.getenv("PORT") or 5911
debug = os.getenv("DEBUG") == "true"

app.run(host="0.0.0.0", port=int(port), debug=debug, workers=1, access_log=True)
