#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# https://github.com/clxjaguar/super8-converter

import sys, os, time, subprocess

if os.name == 'posix':
	mpvPath = 'mpv'
else:
	mpvPath = os.path.dirname(os.path.realpath(__file__))+'\\mpv.exe'

try:
	# sudo apt-get install python3-pyqt5
	# ~ raise("Uncomment this line is to want to force fallback to PyQt4 for testing")
	from PyQt5.QtGui import *
	from PyQt5.QtCore import *
	from PyQt5.QtWidgets import *
	PYQT_VERSION = 5
	print("Using PyQt5")
except:
	# sudo apt-get install python-qtpy python3-qtpy
	from PyQt4.QtGui import *
	from PyQt4.QtCore import *
	PYQT_VERSION = 4
	print("Using PyQt4")


class Indicator(QLabel):
	def __init__(self, text=None, layout=None, gridPlacement=(0,0), gridSpan=(1,1), objectName=None):
		QLabel.__init__(self)
		self.setMinimumWidth(100)
		if text:
			self.setText(text)
		if type(layout) == QGridLayout:
			layout.addWidget(self, gridPlacement[0], gridPlacement[1], gridSpan[0], gridSpan[1])
		elif layout != None:
			layout.addWidget(self)

		self.timer = QTimer()
		self.timer.timeout.connect(self.blinkTimerTimeout)
		self.reset()

	def reset(self):
		self.timer.stop()
		self.setStyleSheet("background: #ff0000;")

	def set(self):
		self.timer.stop()
		self.setStyleSheet("background: #00ff00;")

	def blink(self):
		self.blinkState = True
		self.timer.start(250)
		self.blinkTimerTimeout()

	def blinkTimerTimeout(self):
		self.setStyleSheet("background: %s;" % ('#00ff00' if self.blinkState else '#000000'))
		self.blinkState = not self.blinkState


class Player(QObject):
	cropUpdate = pyqtSignal(str)
	progressUpdate = pyqtSignal(int, str)
	error = pyqtSignal(str)
	executionFinished = pyqtSignal(int)

	def __init__(self, filename, startAt=0, cropDetectLevel=None, cropRect=None, forceFPS=False, mirror=False, outputFile=None, eqDict=None, additionalParameters=None):
		QObject.__init__(self)

		self.proc = None
		self.filename = filename
		self.startAt = startAt
		self.cropDetectLevel = cropDetectLevel
		self.cropRect = cropRect
		self.forceFPS = forceFPS
		self.forcedStop = False
		self.mirror = mirror
		self.outputFile = outputFile
		self.eqDict = eqDict
		self.additionalParameters = additionalParameters

		self.playerThread = QThread()
		self.playerThread.setObjectName("Player Thread")
		self.moveToThread(self.playerThread)
		self.playerThread.started.connect(self.worker)
		self.playerThread.start()

	def worker(self):
		cropDetectKey = "crop="
		runCmd = [mpvPath]

		if self.startAt != 0:
			runCmd+= ['--start='+str(self.startAt)]

		if self.cropDetectLevel:
			runCmd+= ['-v', '--vf-add=cropdetect='+str(self.cropDetectLevel)]

		if self.cropRect:
			runCmd+= ['--vf-add=lavfi=[crop='+self.cropRect+']']

		if self.mirror:
			runCmd+= ['--vf-add=hflip']

		if self.eqDict is not None:
			s = ''
			for p in self.eqDict:
				if s != '': s+=':'
				s+=p+'='+self.eqDict[p]

			runCmd+=['--vf-add=eq='+s]

		if self.forceFPS:
			runCmd+= ['-fps='+str(self.forceFPS), '--no-correct-pts']
			runCmd+= ['--vf-add=fps='+str(self.forceFPS)]

		if self.additionalParameters:
			runCmd+= self.additionalParameters

		runCmd+= [self.filename]

		if self.outputFile:
			runCmd+= ['-o', self.outputFile]

		print("Running:", " ".join(runCmd))

		try:
			self.proc = subprocess.Popen(runCmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)
			lastLines = []
			started = time.time()

			while not self.playerThread.isInterruptionRequested():
				line = self.proc.stdout.readline()
				if line == "": break
				line = line.strip()
				if line == "": continue

				p = line.find(cropDetectKey)
				if p >= 0:
					self.cropUpdate.emit(line[p+len(cropDetectKey):].split()[0])

				if line.find('V: ') >= 0:
					try:
						m1 = line.find('{')
						m2 = line.find('}')
						if m1 >= 0 and m2:
							s = line[m1+1:m2]

							mpos = s.find('min')
							if mpos > 0:
								remainingTime = float(s[0:mpos])*60
								elapsedTime = time.time() - started
								percent = int(99.0 * (elapsedTime/(remainingTime+elapsedTime)))
							else:
								percent = None
						else:
							s = ''; percent = None

					except:
						s = ''; percent = None

					if percent is None:
						try:
							p1 = line.find('(')
							p2 = line.find('%)')
							percent = int(line[p1+1:p2])
						except:
							percent = -1

					self.progressUpdate.emit(percent, s)
				else:
					print(line)
					lastLines = lastLines[-10:] + [line]

			if not self.forcedStop:
				time.sleep(0.2)
				self.proc.terminate()
				if self.proc.returncode:
					self.error.emit("%s\n\n%s finished with return code %s:\n%s" % (" ".join(runCmd), runCmd[0], self.proc.returncode, "\n".join(lastLines)))
				print("Finished with return code:", self.proc.returncode)
				self.executionFinished.emit(self.proc.returncode if self.proc.returncode else 0)
			else:
				self.executionFinished.emit(0)

		except Exception as e:
			self.error.emit(" ".join(runCmd)+"\n\n"+str(e))
			self.executionFinished.emit(-1)
		self.playerThread.quit()
		self.proc = None

	def stop(self):
		self.forcedStop = True
		if self.proc:
			self.proc.terminate()
		self.playerThread.quit()

	def __del__(self):
		self.forcedStop = True
		self.playerThread.quit()


class GUI(QWidget):
	def __init__(self):
		QWidget.__init__(self)
		self.player, self.converter = [None]*2
		self.initUI()
		self.inputFilename = None
		self.defaultInputPath = None
		self.defaultOutputPath = None

	def initUI(self):
		self.setStyleSheet("\
			QLabel { margin: 0px; padding: 0px; } \
			QPushButton::checked { background: #0090ff; } \
			QSplitter::handle:vertical   { image: none; } \
			QSplitter::handle:horizontal { width:  2px; image: none; } \
		");

		layout = QVBoxLayout(self)

		def mkLabel(text=None, layout=None, alignment=Qt.AlignVCenter, gridPlacement=(0,0), gridSpan=(1,1), objectName=None):
			o = QLabel()
			if objectName:
				o.setObjectName(objectName)
			o.setAlignment(alignment)
			if text:
				o.setText(text)
			if type(layout) == QGridLayout:
				layout.addWidget(o, gridPlacement[0], gridPlacement[1], gridSpan[0], gridSpan[1])
			elif layout != None:
				layout.addWidget(o)
			o.setAutoFillBackground(True);
			return o

		def mkButton(text, layout=None, function=None, gridPlacement=(0,0), gridSpan=(1,1), isCheckable=False, objectName=None):
			btn = QPushButton(text)
			btn.setFocusPolicy(Qt.TabFocus)
			btn.setCheckable(isCheckable)
			if objectName:
				btn.setObjectName(objectName)
			if function:
				btn.clicked.connect(function)
			if type(layout) == QGridLayout:
				layout.addWidget(btn, gridPlacement[0], gridPlacement[1], gridSpan[0], gridSpan[1])
			elif layout != None:
				layout.addWidget(btn)
			return btn

		groupBox = QGroupBox("Operations")
		gridLayout = QGridLayout(groupBox)
		layout.addWidget(groupBox)

		self.selectFileBtn = mkButton("Select File", gridLayout, self.selectFileBtnClicked, gridPlacement=(1, 0))
		self.selectFileBtnIndicator = Indicator(None, gridLayout, gridPlacement=(0, 0))

		self.cropDetectBtn = mkButton("Crop Detect", gridLayout, self.cropDetectBtnClicked, gridPlacement=(1, 1), isCheckable=True)
		self.cropDetectBtn.setEnabled(False)
		self.cropDetectIndicator = Indicator(None, gridLayout, gridPlacement=(0, 1))

		self.previewBtn = mkButton("Preview", gridLayout, self.previewBtnClicked, gridPlacement=(1, 2), isCheckable=True)
		self.previewBtn.setEnabled(False)
		self.previewIndicator = Indicator(None, gridLayout, gridPlacement=(0, 2))

		self.runConversionBtn = mkButton("Convert", gridLayout, self.runConversionBtnClicked, gridPlacement=(1, 3), isCheckable=True)
		self.runConversionBtn.setEnabled(False)
		self.runConversionIndicator = Indicator(None, gridLayout, gridPlacement=(0, 3))

		self.inputFileLabel = mkLabel("Input file: <none>", layout)
		self.outputFileLabel = mkLabel("Output file: <none>", layout)

		layout2 = QHBoxLayout()
		mkLabel("Crop-detect at", layout2)
		self.cropDetectAt = QSpinBox()
		self.cropDetectAt.setRange(0, 9999)
		self.cropDetectAt.setValue(60)
		self.cropDetectAt.setSuffix('s')
		layout2.addWidget(self.cropDetectAt)

		mkLabel("Threshold", layout2)

		self.cropDetectLevel = QSpinBox()
		self.cropDetectLevel.setMinimum(1)
		self.cropDetectLevel.setMaximum(255)
		self.cropDetectLevel.setValue(25)
		layout2.addWidget(self.cropDetectLevel)

		mkLabel(":", layout2)
		self.cropRectValue = QLineEdit()
		self.cropRectValue.setMinimumWidth(200)
		self.cropRectValue.textChanged.connect(self.checkCropRect)
		layout2.addWidget(self.cropRectValue)

		layout2.addStretch()
		layout.addLayout(layout2)

		layout2 = QHBoxLayout()
		mkLabel("Force FPS to", layout2)
		self.forceFPS = QSpinBox()
		self.forceFPS.setMinimum(0)
		layout2.addWidget(self.forceFPS)

		mkLabel("Start conversion at", layout2)
		self.startConversionAt = QDoubleSpinBox()
		self.startConversionAt.setRange(0, 9999)
		self.startConversionAt.setSingleStep(0.1)
		self.startConversionAt.setSuffix('s')
		layout2.addWidget(self.startConversionAt)

		self.mirrorBtn = QCheckBox("Mirror")
		layout2.addWidget(self.mirrorBtn)

		layout2.addStretch()
		layout.addLayout(layout2)

		groupBox = QGroupBox("Image EQ")
		gridLayout = QGridLayout(groupBox)
		layout.addWidget(groupBox)

		# https://ffmpeg.org/ffmpeg-filters.html#eq
		self.eqEnableBtn = QCheckBox("Enable EQ")
		def fct(state):
			for sb in self.eqControls:
				sb.setEnabled(state)
		self.eqEnableBtn.clicked.connect(fct)
		gridLayout.addWidget(self.eqEnableBtn)
		h = QLabel('<a href="https://ffmpeg.org/ffmpeg-filters.html#eq">?</a>')
		h.setTextInteractionFlags(Qt.LinksAccessibleByMouse|Qt.TextBrowserInteraction)
		h.setOpenExternalLinks(True)
		gridLayout.addWidget(h, 0, 1)
		self.eqControls = []

		self.eqContrast = QSpinBox()
		self.eqContrast.eqId = 'contrast'
		gridLayout.addWidget(QLabel('Contrast'), 1, 0)
		gridLayout.addWidget(self.eqContrast, 1, 1)
		self.eqControls.append(self.eqContrast)

		self.eqBrightness = QSpinBox()
		self.eqBrightness.eqId = 'brightness'
		gridLayout.addWidget(QLabel('Brightness'), 1, 2)
		gridLayout.addWidget(self.eqBrightness, 1, 3)
		self.eqControls.append(self.eqBrightness)

		self.eqSaturation = QSpinBox()
		self.eqSaturation.eqId = 'saturation'
		gridLayout.addWidget(QLabel('Saturation'), 1, 4)
		gridLayout.addWidget(self.eqSaturation, 1, 5)
		self.eqControls.append(self.eqSaturation)

		self.eqGammaR = QSpinBox()
		self.eqGammaR.eqId = 'gamma_r'
		gridLayout.addWidget(QLabel('Gamma: Red'), 2, 0)
		gridLayout.addWidget(self.eqGammaR, 2, 1)
		self.eqControls.append(self.eqGammaR)

		self.eqGammaG = QSpinBox()
		self.eqGammaG.eqId = 'gamma_g'
		gridLayout.addWidget(QLabel('Green'), 2, 2)
		gridLayout.addWidget(self.eqGammaG, 2, 3)
		self.eqControls.append(self.eqGammaG)

		self.eqGammaB = QSpinBox()
		self.eqGammaB.eqId = 'gamma_b'
		gridLayout.addWidget(QLabel('Blue'), 2, 4)
		gridLayout.addWidget(self.eqGammaB, 2, 5)
		self.eqControls.append(self.eqGammaB)

		self.eqGammaWeight = QSpinBox()
		self.eqGammaWeight.eqId = 'gamma_weight'
		gridLayout.addWidget(QLabel('Weight'), 2, 6)
		gridLayout.addWidget(self.eqGammaWeight, 2, 7)
		self.eqControls.append(self.eqGammaWeight)

		for sb in self.eqControls:
			sb.setMinimum(10)
			sb.setMaximum(1000)
			sb.setValue(100)
			sb.setSuffix('%')
			sb.setEnabled(False)

		self.eqContrast.setMinimum(-1000)
		self.eqContrast.setMaximum(1000)
		self.eqContrast.setValue(130)
		def fct():
			if self.eqBrightness.value() < 0:
				self.eqBrightness.setPrefix('  ')
			else:
				self.eqBrightness.setPrefix('+')
		self.eqBrightness.setPrefix('+')
		self.eqBrightness.valueChanged.connect(fct)
		self.eqBrightness.setMinimum(-100)
		self.eqBrightness.setMaximum(100)
		self.eqBrightness.setValue(0)
		self.eqSaturation.setMinimum(0)
		self.eqSaturation.setMaximum(300)
		self.eqGammaB.setValue(30)
		self.eqGammaWeight.setMaximum(100)
		self.eqGammaWeight.setValue(50)


		self.progressBar = QProgressBar()
		self.progressBar.setVisible(False)
		layout.addWidget(self.progressBar)

		layout.addStretch()

		url = mkLabel('<a href="http://clx.freeshell.org/">clx.freeshell.org</a>', layout, Qt.AlignRight)
		url.setTextInteractionFlags(Qt.LinksAccessibleByMouse|Qt.TextBrowserInteraction)
		url.setOpenExternalLinks(True)

		self.setWindowTitle(u"8mm Captured Video Converter")
		self.setWindowFlags(Qt.WindowStaysOnTopHint)
		self.setAcceptDrops(True)
		self.show()

	def dragEnterEvent(self, e):
		if e.mimeData().hasUrls:
			filename = e.mimeData().urls()[0].toLocalFile()
			for ext in ['avi', 'mp4', 'mkv']:
				if filename.endswith(ext):
					e.accept()
					return
		e.ignore()

	def dropEvent(self, e):
		if e.mimeData().hasUrls:
			filename = e.mimeData().urls()[0].toLocalFile()
			e.accept()
			self.selectFile(filename)
		else:
			e.ignore()

	def selectFileBtnClicked(self):
		filename = QFileDialog.getOpenFileName(self, 'Select captured video file to convert', self.defaultInputPath, 'Unconverted files (*.avi *.mp4);;All (*)')[0]
		if not filename:
			return
		self.selectFile(filename)

	def selectFile(self, filename):
		try:
			fd = open(filename, 'r')
			fd.close()
		except Exception as e:
			QMessageBox.critical(self, "Input File Error", str(e))
			return

		self.inputFilename = filename
		self.defaultInputPath = filename
		if self.defaultOutputPath is None:
			self.defaultOutputPath = os.path.dirname(filename)
		self.inputFileLabel.setText("Input file: "+os.path.basename(self.inputFilename))
		self.outputFileLabel.setText("Output file: <none>"); self.outputFilename = ""

		self.cropDetectBtn.setEnabled(True)
		self.selectFileBtnIndicator.set()
		self.cropDetectIndicator.reset()
		self.previewIndicator.reset()
		self.runConversionIndicator.reset()
		self.progressBar.setVisible(False)
		self.startConversionAt.setValue(0)
		self.checkCropRect()


	def cropDetectBtnClicked(self, state):
		if self.player:
			self.player.stop()

		if state:
			self.player = Player(self.inputFilename, startAt=self.cropDetectAt.value(), cropDetectLevel=self.cropDetectLevel.value(), forceFPS=25)
			self.player.cropUpdate.connect(self.cropUpdate)
			self.player.error.connect(self.showError)
			self.player.executionFinished.connect(self.cropDetectFinished)

			self.cropRectValue.setText('')
			self.previewIndicator.reset()
			self.runConversionIndicator.reset()
			self.cropDetectIndicator.blink()
			self.selectFileBtn.setEnabled(False)
			self.cropDetectLevel.setEnabled(False)
			self.cropDetectTimer = QTimer()
			self.cropDetectTimer.timeout.connect(lambda: self.cropDetectBtnClicked(False))
			self.cropRectValue.blockSignals(True)

		else:
			self.cropDetectFinished(0)
			self.cropDetectTimer.stop()
			self.cropDetectLevel.setEnabled(True)
			self.cropRectValue.blockSignals(False)

	def cropUpdate(self, s):
		oldtxt = self.cropRectValue.text()
		if s == oldtxt:
			return

		rect = s.split(':')
		if len(rect) == 4 and rect[0][0] != '-' and rect[1][0] != '-' and rect[2][0] != '-' and rect[3][0] != '-':

			if oldtxt == "":
				self.previewBtn.setEnabled(True)
			sys.stdout.write("\a")
			self.cropRectValue.setText(s)
			self.cropDetectTimer.start(20000)

	def checkCropRect(self):
		try:
			rect = self.cropRectValue.text().split(':')
			if self.inputFilename is not None:
				if len(rect) == 4 and int(rect[0]) >= 0 and int(rect[1]) >= 0 and int(rect[2]) >= 0 and int(rect[3]) >= 0:
					self.previewBtn.setEnabled(True)
					self.runConversionBtn.setEnabled(True)
					return True
			return False
		except:
			return False

	def showError(self, s):
		QMessageBox.warning(self, "Error", s)

	def cropDetectFinished(self, returncode):
		self.cropDetectBtn.setChecked(False)
		self.selectFileBtn.setEnabled(True)
		self.cropDetectLevel.setEnabled(True)
		rect = self.cropRectValue.text().split(':')
		if len(rect) == 4 and rect[0][0] != '-' and rect[1][0] != '-' and rect[2][0] != '-' and rect[3][0] != '-':
			self.previewBtn.setEnabled(True)
			self.runConversionBtn.setEnabled(True)
			self.cropDetectIndicator.set()
		else:
			self.cropDetectIndicator.reset()

	def makeEqDict(self):
		eqDict={'gamma_r':'0.1'}
		if not self.eqEnableBtn.isChecked():
			return None

		eqDict = {}
		for sb in self.eqControls:
			if sb.value() != 100.0:
				eqDict[sb.eqId]=str(sb.value() / 100.0)

		return eqDict

	def previewBtnClicked(self, state):
		if self.player:
			self.player.stop()

		if state:
			self.player = Player(self.inputFilename, cropRect=self.cropRectValue.text(), startAt=self.startConversionAt.value(), forceFPS=self.forceFPS.value(), mirror=self.mirrorBtn.isChecked(), eqDict=self.makeEqDict())
			self.player.error.connect(self.showError)
			self.player.executionFinished.connect(self.previewFinished)
			self.previewIndicator.blink()
			self.selectFileBtn.setEnabled(False)
		else:
			self.previewFinished(0)

	def previewFinished(self, returncode):
		self.previewBtn.setChecked(False)
		self.selectFileBtn.setEnabled(True)
		if returncode == 0:
			self.previewIndicator.set()
		else:
			self.previewIndicator.reset()

	def runConversionBtnClicked(self, state):
		if state:
			defaultFilename = os.path.splitext(os.path.basename(self.inputFilename))[0]+'.mp4'
			if self.defaultOutputPath:
				defaultFilename = self.defaultOutputPath+'/'+defaultFilename
			filters = 'MP4 files (*.mp4);;All (*)'
			dialog = QFileDialog(self, "Select output filename", defaultFilename, filters)
			dialog.setDefaultSuffix(".mp4");
			dialog.setAcceptMode(QFileDialog.AcceptSave);
			if dialog.exec():
				self.defaultOutputPath = os.path.dirname(dialog.selectedFiles()[0])
				self.runConversion(dialog.selectedFiles()[0])
			else:
				self.runConversionBtn.setChecked(False)
		else:
			if self.converter:
				self.converter.executionFinished.disconnect()
				self.converter.stop()
			self.runConversionIndicator.reset()

	def runConversion(self, filename):
		self.progressBar.setVisible(True)
		self.progressBar.setFormat("")
		self.progressBar.setValue(0)

		self.outputFilename = filename
		self.outputFileLabel.setText("Output file: "+os.path.basename(self.outputFilename))

		self.converter = Player(self.inputFilename, cropRect=self.cropRectValue.text(), startAt=self.startConversionAt.value(), forceFPS=self.forceFPS.value(), mirror=self.mirrorBtn.isChecked(), outputFile=self.outputFilename, eqDict=self.makeEqDict())

		self.converter.error.connect(self.showError)
		self.converter.progressUpdate.connect(self.progressUpdate)
		self.converter.executionFinished.connect(self.conversionFinished)
		self.runConversionIndicator.blink()

	def progressUpdate(self, percent, info):
		if info:
			self.progressBar.setFormat(info)
		else:
			self.progressBar.setFormat("%v%")
		self.progressBar.setValue(percent)

	def conversionFinished(self, returncode):
		self.runConversionBtn.setChecked(False)
		if returncode == 0:
			self.runConversionIndicator.set()
			self.progressBar.setValue(100)
		else:
			self.runConversionIndicator.reset()
		sys.stdout.write('\a')
		sys.stdout.flush()

	def closeEvent(self, event):
		if self.player:
			self.player.stop()
			self.player = None
		if self.converter:
			self.converter.stop()
			self.converter = None
		event.accept()


def main():
	app = QApplication(sys.argv)
	m1 = GUI()
	app.installEventFilter(m1)
	ret = app.exec_()
	sys.exit(ret)

if __name__ == '__main__':
	main()
