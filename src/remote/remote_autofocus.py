from flask import Flask, Response

app = Flask(__name__)


@app.route("/", methods=["GET"])
def ping_route():
    return "Hello World"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False, use_reloader=False)
