# coding=utf-8
__author__ = "Gina Häußge <osd@foosel.net>"
__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'

from octoprint.settings import settings

import os
import threading
import urllib
import time
import subprocess
import fnmatch

def getFinishedTimelapses():
	files = []
	basedir = settings().getBaseFolder("timelapse")
	for osFile in os.listdir(basedir):
		if not fnmatch.fnmatch(osFile, "*.mpg"):
			continue
		files.append({
			"name": osFile,
			"size": os.stat(os.path.join(basedir, osFile)).st_size
		})
	return files

class Timelapse(object):
	def __init__(self):
		self._imageNumber = None
		self._inTimelapse = False
		self._gcodeFile = None

		self._captureDir = settings().getBaseFolder("timelapse_tmp")
		self._movieDir = settings().getBaseFolder("timelapse")
		self._snapshotUrl = settings().get(["webcam", "snapshot"])

		self._renderThread = None
		self._captureMutex = threading.Lock()

	def onPrintjobStarted(self, gcodeFile):
		self.startTimelapse(gcodeFile)

	def onPrintjobStopped(self):
		self.stopTimelapse()

	def onPrintjobProgress(self, oldPos, newPos, percentage):
		pass

	def onZChange(self, oldZ, newZ):
		pass

	def startTimelapse(self, gcodeFile):
		self.cleanCaptureDir()

		self._imageNumber = 0
		self._inTimelapse = True
		self._gcodeFile = os.path.basename(gcodeFile)

	def stopTimelapse(self):
		self._renderThread = threading.Thread(target=self._createMovie)
		self._renderThread.daemon = True
		self._renderThread.start()

		self._imageNumber = None
		self._inTimelapse = False

	def captureImage(self):
		if self._captureDir is None:
			return

		with self._captureMutex:
			filename = os.path.join(self._captureDir, "tmp_%05d.jpg" % (self._imageNumber))
			self._imageNumber += 1;

		captureThread = threading.Thread(target=self._captureWorker, kwargs={"filename": filename})
		captureThread.daemon = True
		captureThread.start()

	def _captureWorker(self, filename):
		urllib.urlretrieve(self._snapshotUrl, filename)

	def _createMovie(self):
		ffmpeg = settings().get(["webcam", "ffmpeg"])
		bitrate = settings().get(["webcam", "bitrate"])
		if ffmpeg is None or bitrate is None:
			return

		input = os.path.join(self._captureDir, "tmp_%05d.jpg")
		output = os.path.join(self._movieDir, "%s_%s.mpg" % (os.path.splitext(self._gcodeFile)[0], time.strftime("%Y%m%d%H%M%S")))
		subprocess.call([
			ffmpeg, '-i', input, '-vcodec', 'mpeg2video', '-pix_fmt', 'yuv420p', '-r', '25', '-y',
			 '-b:v', bitrate, '-f', 'vob', output
		])

	def cleanCaptureDir(self):
		if not os.path.isdir(self._captureDir):
			return

		for filename in os.listdir(self._captureDir):
			if not fnmatch.fnmatch(filename, "*.jpg"):
				continue
			os.remove(os.path.join(self._captureDir, filename))

class ZTimelapse(Timelapse):
	def __init__(self):
		Timelapse.__init__(self)

	def onZChange(self, oldZ, newZ):
		self.captureImage()

class TimedTimelapse(Timelapse):
	def __init__(self, interval=1):
		Timelapse.__init__(self)

		self._interval = interval
		if self._interval < 1:
			self._interval = 1 # force minimum interval of 1s

		self._timerThread = None

	def onPrintjobStarted(self, filename):
		Timelapse.onPrintjobStarted(self, filename)
		if self._timerThread is not None:
			return

		self._timerThread = threading.Thread(target=self.timerWorker)
		self._timerThread.daemon = True
		self._timerThread.start()

	def timerWorker(self):
		while self._inTimelapse:
			self.captureImage()
			time.sleep(self._interval)
