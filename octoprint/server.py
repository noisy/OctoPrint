# coding=utf-8
__author__ = "Gina Häußge <osd@foosel.net>"
__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'

from flask import Flask, request, render_template, jsonify, send_from_directory, abort, url_for
from werkzeug.utils import secure_filename
import tornadio2

import os
import threading
import logging, logging.config

from octoprint.printer import Printer, getConnectionOptions
from octoprint.settings import settings
import octoprint.timelapse as timelapse
import octoprint.gcodefiles as gcodefiles
import octoprint.util as util

BASEURL = "/ajax/"
SUCCESS = {}

UPLOAD_FOLDER = settings().getBaseFolder("uploads")

app = Flask("octoprint")
gcodeManager = gcodefiles.GcodeManager()
printer = Printer(gcodeManager)

@app.route("/")
def index():
	return render_template(
		"index.html",
		webcamStream=settings().get(["webcam", "stream"]),
		enableTimelapse=(settings().get(["webcam", "snapshot"]) is not None and settings().get(["webcam", "ffmpeg"]) is not None),
		enableGCodeVisualizer=settings().get(["feature", "gCodeVisualizer"])
	)

#~~ Printer state

class PrinterStateConnection(tornadio2.SocketConnection):
	def __init__(self, session, endpoint=None):
		tornadio2.SocketConnection.__init__(self, session, endpoint)

		self._logger = logging.getLogger(__name__)

		self._temperatureBacklog = []
		self._temperatureBacklogMutex = threading.Lock()
		self._logBacklog = []
		self._logBacklogMutex = threading.Lock()
		self._messageBacklog = []
		self._messageBacklogMutex = threading.Lock()

	def on_open(self, info):
		self._logger.info("New connection from client")
		printer.registerCallback(self)
		gcodeManager.registerCallback(self)

	def on_close(self):
		self._logger.info("Closed client connection")
		printer.unregisterCallback(self)
		gcodeManager.unregisterCallback(self)

	def on_message(self, message):
		pass

	def sendCurrentData(self, data):
		# add current temperature, log and message backlogs to sent data
		with self._temperatureBacklogMutex:
			temperatures = self._temperatureBacklog
			self._temperatureBacklog = []

		with self._logBacklogMutex:
			logs = self._logBacklog
			self._logBacklog = []

		with self._messageBacklogMutex:
			messages = self._messageBacklog
			self._messageBacklog = []

		data.update({
			"temperatures": temperatures,
			"logs": logs,
			"messages": messages
		})
		self.emit("current", data)

	def sendHistoryData(self, data):
		self.emit("history", data)

	def sendUpdateTrigger(self, type):
		self.emit("updateTrigger", type)

	def addLog(self, data):
		with self._logBacklogMutex:
			self._logBacklog.append(data)

	def addMessage(self, data):
		with self._messageBacklogMutex:
			self._messageBacklog.append(data)

	def addTemperature(self, data):
		with self._temperatureBacklogMutex:
			self._temperatureBacklog.append(data)

#~~ Printer control

@app.route(BASEURL + "control/connectionOptions", methods=["GET"])
def connectionOptions():
	return jsonify(getConnectionOptions())

@app.route(BASEURL + "control/connect", methods=["POST"])
def connect():
	port = None
	baudrate = None
	if "port" in request.values.keys():
		port = request.values["port"]
	if "baudrate" in request.values.keys():
		baudrate = request.values["baudrate"]
	if "save" in request.values.keys():
		settings().set(["serial", "port"], port)
		settings().setInt(["serial", "baudrate"], baudrate)
		settings().save()
	printer.connect(port=port, baudrate=baudrate)
	return jsonify(state="Connecting")

@app.route(BASEURL + "control/disconnect", methods=["POST"])
def disconnect():
	printer.disconnect()
	return jsonify(state="Offline")

@app.route(BASEURL + "control/command", methods=["POST"])
def printerCommand():
	if "application/json" in request.headers["Content-Type"]:
		data = request.json

		parameters = {}
		if "parameters" in data.keys(): parameters = data["parameters"]

		commands = []
		if "command" in data.keys(): commands = [data["command"]]
		elif "commands" in data.keys(): commands = data["commands"]

		commandsToSend = []
		for command in commands:
			commandToSend = command
			if len(parameters) > 0:
				commandToSend = command % parameters
			commandsToSend.append(commandToSend)

		printer.commands(commandsToSend)

	return jsonify(SUCCESS)

@app.route(BASEURL + "control/print", methods=["POST"])
def printGcode():
	printer.startPrint()
	return jsonify(SUCCESS)

@app.route(BASEURL + "control/pause", methods=["POST"])
def pausePrint():
	printer.togglePausePrint()
	return jsonify(SUCCESS)

@app.route(BASEURL + "control/cancel", methods=["POST"])
def cancelPrint():
	printer.cancelPrint()
	return jsonify(SUCCESS)

@app.route(BASEURL + "control/temperature", methods=["POST"])
def setTargetTemperature():
	if not printer.isOperational():
		return jsonify(SUCCESS)

	elif request.values.has_key("temp"):
		# set target temperature
		temp = request.values["temp"]
		printer.command("M104 S" + temp)

	elif request.values.has_key("bedTemp"):
		# set target bed temperature
		bedTemp = request.values["bedTemp"]
		printer.command("M140 S" + bedTemp)

	return jsonify(SUCCESS)

@app.route(BASEURL + "control/jog", methods=["POST"])
def jog():
	if not printer.isOperational() or printer.isPrinting():
		# do not jog when a print job is running or we don't have a connection
		return jsonify(SUCCESS)

	(movementSpeedX, movementSpeedY, movementSpeedZ, movementSpeedE) = settings().get(["printerParameters", "movementSpeed", ["x", "y", "z", "e"]])
	if "x" in request.values.keys():
		# jog x
		x = request.values["x"]
		printer.commands(["G91", "G1 X%s F%d" % (x, movementSpeedX), "G90"])
	if "y" in request.values.keys():
		# jog y
		y = request.values["y"]
		printer.commands(["G91", "G1 Y%s F%d" % (y, movementSpeedY), "G90"])
	if "z" in request.values.keys():
		# jog z
		z = request.values["z"]
		printer.commands(["G91", "G1 Z%s F%d" % (z, movementSpeedZ), "G90"])
	if "homeXY" in request.values.keys():
		# home x/y
		printer.command("G28 X0 Y0")
	if "homeZ" in request.values.keys():
		# home z
		printer.command("G28 Z0")
	if "extrude" in request.values.keys():
		# extrude/retract
		length = request.values["extrude"]
		printer.commands(["G91", "G1 E%s F%d" % (length, movementSpeedE), "G90"])

	return jsonify(SUCCESS)

@app.route(BASEURL + "control/speed", methods=["GET"])
def getSpeedValues():
	return jsonify(feedrate=printer.feedrateState())

@app.route(BASEURL + "control/speed", methods=["POST"])
def speed():
	if not printer.isOperational():
		return jsonify(SUCCESS)

	for key in ["outerWall", "innerWall", "fill", "support"]:
		if key in request.values.keys():
			value = int(request.values[key])
			printer.setFeedrateModifier(key, value)

	return getSpeedValues()

@app.route(BASEURL + "control/custom", methods=["GET"])
def getCustomControls():
	customControls = settings().get(["controls"])
	return jsonify(controls=customControls)

#~~ GCODE file handling

@app.route(BASEURL + "gcodefiles", methods=["GET"])
def readGcodeFiles():
	return jsonify(files=gcodeManager.getAllFileData())

@app.route(BASEURL + "gcodefiles/<path:filename>", methods=["GET"])
def readGcodeFile(filename):
	return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

@app.route(BASEURL + "gcodefiles/upload", methods=["POST"])
def uploadGcodeFile():
	filename = None
	if "gcode_file" in request.files.keys():
		file = request.files["gcode_file"]
		filename = gcodeManager.addFile(file)
	return jsonify(files=gcodeManager.getAllFileData(), filename=filename)

@app.route(BASEURL + "gcodefiles/load", methods=["POST"])
def loadGcodeFile():
	if "filename" in request.values.keys():
		filename = gcodeManager.getAbsolutePath(request.values["filename"])
		if filename is not None:
			printer.loadGcode(filename)
	return jsonify(SUCCESS)

@app.route(BASEURL + "gcodefiles/delete", methods=["POST"])
def deleteGcodeFile():
	if "filename" in request.values.keys():
		filename = request.values["filename"]
		gcodeManager.removeFile(filename)
	return readGcodeFiles()

#~~ timelapse handling

@app.route(BASEURL + "timelapse", methods=["GET"])
def getTimelapseData():
	lapse = printer.getTimelapse()

	type = "off"
	additionalConfig = {}
	if lapse is not None and isinstance(lapse, timelapse.ZTimelapse):
		type = "zchange"
	elif lapse is not None and isinstance(lapse, timelapse.TimedTimelapse):
		type = "timed"
		additionalConfig = {
			"interval": lapse.interval
		}

	files = timelapse.getFinishedTimelapses()
	for file in files:
		file["url"] = url_for("downloadTimelapse", filename=file["name"])

	return jsonify({
	"type": type,
	"config": additionalConfig,
	"files": files
	})

@app.route(BASEURL + "timelapse/<filename>", methods=["GET"])
def downloadTimelapse(filename):
	if util.isAllowedFile(filename, set(["mpg"])):
		return send_from_directory(settings().getBaseFolder("timelapse"), filename, as_attachment=True)

@app.route(BASEURL + "timelapse/<filename>", methods=["DELETE"])
def deleteTimelapse(filename):
	if util.isAllowedFile(filename, set(["mpg"])):
		secure = os.path.join(settings().getBaseFolder("timelapse"), secure_filename(filename))
		if os.path.exists(secure):
			os.remove(secure)
	return getTimelapseData()

@app.route(BASEURL + "timelapse/config", methods=["POST"])
def setTimelapseConfig():
	if request.values.has_key("type"):
		type = request.values["type"]
		lapse = None
		if "zchange" == type:
			lapse = timelapse.ZTimelapse()
		elif "timed" == type:
			interval = 10
			if request.values.has_key("interval"):
				try:
					interval = int(request.values["interval"])
				except ValueError:
					pass
			lapse = timelapse.TimedTimelapse(interval)
		printer.setTimelapse(lapse)

	return getTimelapseData()

#~~ settings

@app.route(BASEURL + "settings", methods=["GET"])
def getSettings():
	s = settings()

	[movementSpeedX, movementSpeedY, movementSpeedZ, movementSpeedE] = s.get(["printerParameters", "movementSpeed", ["x", "y", "z", "e"]])

	return jsonify({
		"appearance": {
			"name": s.get(["appearance", "name"]),
			"color": s.get(["appearance", "color"])
		},
		"printer": {
			"movementSpeedX": movementSpeedX,
			"movementSpeedY": movementSpeedY,
			"movementSpeedZ": movementSpeedZ,
			"movementSpeedE": movementSpeedE,
		},
		"webcam": {
			"streamUrl": s.get(["webcam", "stream"]),
			"snapshotUrl": s.get(["webcam", "snapshot"]),
			"ffmpegPath": s.get(["webcam", "ffmpeg"]),
			"bitrate": s.get(["webcam", "bitrate"]),
			"watermark": s.getBoolean(["webcam", "watermark"])
		},
		"feature": {
			"gcodeViewer": s.getBoolean(["feature", "gCodeVisualizer"]),
			"waitForStart": s.getBoolean(["feature", "waitForStartOnConnect"])
		},
		"folder": {
			"uploads": s.getBaseFolder("uploads"),
			"timelapse": s.getBaseFolder("timelapse"),
			"timelapseTmp": s.getBaseFolder("timelapse_tmp"),
			"logs": s.getBaseFolder("logs")
		},
		"temperature": {
			"profiles": s.get(["temperature", "profiles"])
		}
	})

@app.route(BASEURL + "settings", methods=["POST"])
def setSettings():
	if "application/json" in request.headers["Content-Type"]:
		data = request.json
		s = settings()

		if "appearance" in data.keys():
			if "name" in data["appearance"].keys(): s.set(["appearance", "name"], data["appearance"]["name"])
			if "color" in data["appearance"].keys(): s.set(["appearance", "color"], data["appearance"]["color"])

		if "printer" in data.keys():
			if "movementSpeedX" in data["printer"].keys(): s.setInt(["printerParameters", "movementSpeed", "x"], data["printer"]["movementSpeedX"])
			if "movementSpeedY" in data["printer"].keys(): s.setInt(["printerParameters", "movementSpeed", "y"], data["printer"]["movementSpeedY"])
			if "movementSpeedZ" in data["printer"].keys(): s.setInt(["printerParameters", "movementSpeed", "z"], data["printer"]["movementSpeedZ"])
			if "movementSpeedE" in data["printer"].keys(): s.setInt(["printerParameters", "movementSpeed", "e"], data["printer"]["movementSpeedE"])

		if "webcam" in data.keys():
			if "streamUrl" in data["webcam"].keys(): s.set(["webcam", "stream"], data["webcam"]["streamUrl"])
			if "snapshotUrl" in data["webcam"].keys(): s.set(["webcam", "snapshot"], data["webcam"]["snapshotUrl"])
			if "ffmpegPath" in data["webcam"].keys(): s.set(["webcam", "ffmpeg"], data["webcam"]["ffmpegPath"])
			if "bitrate" in data["webcam"].keys(): s.set(["webcam", "bitrate"], data["webcam"]["bitrate"])
			if "watermark" in data["webcam"].keys(): s.setBoolean(["webcam", "watermark"], data["webcam"]["watermark"])

		if "feature" in data.keys():
			if "gcodeViewer" in data["feature"].keys(): s.setBoolean(["feature", "gCodeVisualizer"], data["feature"]["gcodeViewer"])
			if "waitForStart" in data["feature"].keys(): s.setBoolean(["feature", "waitForStartOnConnect"], data["feature"]["waitForStart"])

		if "folder" in data.keys():
			if "uploads" in data["folder"].keys(): s.setBaseFolder("uploads", data["folder"]["uploads"])
			if "timelapse" in data["folder"].keys(): s.setBaseFolder("timelapse", data["folder"]["timelapse"])
			if "timelapseTmp" in data["folder"].keys(): s.setBaseFolder("timelapse_tmp", data["folder"]["timelapseTmp"])
			if "logs" in data["folder"].keys(): s.setBaseFolder("logs", data["folder"]["logs"])

		if "temperature" in data.keys():
			if "profiles" in data["temperature"].keys(): s.set(["temperature", "profiles"], data["temperature"]["profiles"])

		s.save()

	return getSettings()

#~~ startup code

def run(host = "0.0.0.0", port = 5000, debug = False):
	from tornado.wsgi import WSGIContainer
	from tornado.httpserver import HTTPServer
	from tornado.ioloop import IOLoop
	from tornado.web import Application, FallbackHandler

	logging.getLogger(__name__).info("Listening on http://%s:%d" % (host, port))
	app.debug = debug

	router = tornadio2.TornadioRouter(PrinterStateConnection)
	tornado_app = Application(router.urls + [
		(".*", FallbackHandler, {"fallback": WSGIContainer(app)})
	])
	server = HTTPServer(tornado_app)
	server.listen(port, address=host)
	IOLoop.instance().start()

def initLogging():
	config = {
		"version": 1,
		"formatters": {
			"simple": {
				"format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
			}
		},
		"handlers": {
			"console": {
				"class": "logging.StreamHandler",
				"level": "DEBUG",
				"formatter": "simple",
				"stream": "ext://sys.stdout"
			},
			"file": {
				"class": "logging.handlers.TimedRotatingFileHandler",
				"level": "DEBUG",
				"formatter": "simple",
				"when": "D",
				"backupCount": "1",
				"filename": os.path.join(settings().getBaseFolder("logs"), "octoprint.log")
			}
		},
		"loggers": {
			"octoprint.gcodefiles": {
				"level": "DEBUG"
			}
		},
		"root": {
			"level": "INFO",
			"handlers": ["console", "file"]
		}
	}
	logging.config.dictConfig(config)

def main():
	from optparse import OptionParser

	defaultHost = settings().get(["server", "host"])
	defaultPort = settings().get(["server", "port"])

	parser = OptionParser(usage="usage: %prog [options]")
	parser.add_option("-d", "--debug", action="store_true", dest="debug",
		help="Enable debug mode")
	parser.add_option("--host", action="store", type="string", default=defaultHost, dest="host",
		help="Specify the host on which to bind the server, defaults to %s if not set" % (defaultHost))
	parser.add_option("--port", action="store", type="int", default=defaultPort, dest="port",
		help="Specify the port on which to bind the server, defaults to %s if not set" % (defaultPort))
	(options, args) = parser.parse_args()

	initLogging()
	run(host=options.host, port=options.port, debug=options.debug)

if __name__ == "__main__":
	main()
