# coding: utf-8
from builtins import zip
from builtins import str
from builtins import range

from OpenGL.GL import *
from OpenGL.GL import shaders

from PyQt5.QtCore import pyqtSignal, QObject, QPoint, QLineF, QSize, QThread, Qt
from PyQt5.QtGui import (
        QTransform,
        QPainter,
        QImage,
        QFontMetrics,
        QFont,
        QColor,
        QPixmap,
        QOpenGLContext,
        QOffscreenSurface,
        QOpenGLTexture,
        QOpenGLFramebufferObjectFormat,
        QOpenGLFramebufferObject)
from PyQt5.QtWidgets import (
        QGraphicsScene,
        QApplication,
        QGraphicsItemGroup,
        QGraphicsTextItem,
        QGraphicsPixmapItem,
        QGraphicsLineItem)
from PyQt5.QtOpenGL import QGLFormat, QGLContext

import numpy
from math import log, ceil, exp

from .utilities import complete_filename, format_

def roundUpSize(size):
    """return size roudup to the nearest power of 2"""
    return QSize(pow(2, ceil(log(size.width())/log(2))),
                 pow(2, ceil(log(size.height())/log(2))))

class ColorLegend(QGraphicsScene):
    """A legend provides the symbology for a layer.
    The legend is responsible for the translation of values into color.
    For performace and flexibility reasons the legend provide shader
    functions that will take a value and return a color.
    """

    symbologyChanged = pyqtSignal()

    __pixelColorContinuous = """
        vec4 pixelColor(float value)
        {
            float normalizedValue = clamp(
                logscale
                ? (log(value)-log(minValue))/(log(maxValue)-log(minValue))
                : (value-minValue)/(maxValue-minValue)
                , 0.f, 1.f);
            return texture2D(tex, vec2(.5f, normalizedValue));
        }
        """


    def __init__(self, parent=None):
        #QGraphicsScene.__init__(self, parent)
        super(ColorLegend, self).__init__(parent)
        self.__minValue = 0
        self.__maxValue = 1
        self.__transparency = 0
        self.__uniformLocations = {}
        self.__title = "no title"
        self.__colorRampFile = ColorLegend.availableRamps()[u"Bleu - Rouge"]
        self.__colorRamp = QImage(self.__colorRampFile)
        self.__units = ""
        self.__scale = "linear"
        self.__pixelColor = ColorLegend.__pixelColorContinuous
        self.__graduation = []
        self.__graduated = False
        self.__maskUnits = False
        self.__nbClass = len(self.__graduation)
        self.tex = None

    @staticmethod
    def availableRamps():
        return {u"Brûlé": complete_filename('images/ramp_burn_continuous.svg'),
                u"Bleu - Mauve": complete_filename('images/ramp_blue_purple_discrete.svg'),
                u"Bleu - Rouge": complete_filename('images/ramp_blue_red_continuous.svg')}

    def graduated(self):
        """
        Getter for graduated attribute. Graduated is boolean

        """
        return self.__graduated

    def toggleGraduation(self, flag):
        """
        Activate or remove graduate symbology by sending pixelColor code.

        """
        self.__graduated = bool(flag)
        if self.__graduated:
            self.__pixelColor = "vec4 pixelColor(float value)\n{\n"

            for c, min_, max_ in self.__graduation:
                self.__pixelColor += "    if (float(%g) < value && value <= float(%g)) return vec4(%g, %g, %g, 1.);\n"%(
                        min_, max_, c.redF(), c.greenF(), c.blueF())
            self.__pixelColor += "    return vec4(0., 0., 0., 0.);\n"
            self.__pixelColor += "}\n";
        else:
            self.__pixelColor = ColorLegend.__pixelColorContinuous
        self.symbologyChanged.emit()

    def setGraduation(self, graduation):
        """graduation is a list of tuple (color, min, max) the alpha componant is not considered"""
        self.__graduation = graduation
        self.__nbClass =  len(graduation)
        self.toggleGraduation(bool(self.__graduation))

    def graduation(self):
        """
        Getter for graduation attribute. Graduation is a list of tuple (Qcolor, min, max)

        """
        return self.__graduation

    def _fragmentShader(self):
        """Return a string containing the definition of the GLSL pixel shader
            vec4 pixelColor(float value)
        This may contain global shader variables and should therefore
        be included in the fragment shader between the global variables
        definition and the main() declaration.
        Note that:
            varying float value
        must be defined by the vertex shader
        """
        return """
            varying float value;
            varying float w;
            varying vec3 normal;
            varying vec4 ecPos;
            uniform float transparency;
            uniform float minValue;
            uniform float maxValue;
            uniform bool logscale;
            uniform bool withNormals;
            uniform sampler2D tex;
            """+self.__pixelColor+"""
            void main()
            {
                vec3 lightDir = vec3(gl_LightSource[0].position-ecPos);
                if (withNormals){
                    gl_FragColor.rgb = pixelColor(value).rgb *
                        max(dot(normalize(normal), normalize(lightDir)),0.0);
                    gl_FragColor.a = 1.;
                }
                else {
                    gl_FragColor = pixelColor(value)*(1.-transparency);
                }
            }
            """

    def nbClass(self):
        """
        Getter for nbClass attribute. Nbclass is a int used for graduated symbology

        """
        return self.__nbClass

    def setNbClass(self, nbClass):
        """
        Setter for nbClass attribute. Nbclass is a int used for graduated symbology

        """
        self.__nbClass= nbClass

    def values(self, nbValues=7):
        """Return list of numerical values at 'equal' or 'logequal' intervals """
        values = []
        for i in range(nbValues):
            alpha = 1. - float(i)/(nbValues-1)
            # inverse of the scale function in shader
            value = exp(alpha*(log(self.__maxValue)-log(self.__minValue)) + log(self.__minValue))\
                    if self.__scale == "log" else\
                    self.__minValue + alpha*(self.__maxValue-self.__minValue)
            values.append(value)
        return values

    def image(self):
        """Return an image representing the legend"""
        self.__refresh()

        sz = self.sceneRect().size().toSize()
        img = QImage(
                sz.width(),
                sz.height(),
                self.__colorRamp.format())
        img.fill(Qt.transparent)
        with QPainter(img) as p:
            self.render(p)
        return img

    #def render(self, painter, target = QRectF(), source = QRectF(), aspectRatioMode = Qt.KeepAspectRatio):
    #    self.__refresh()
    #    QGraphicsScene.render(self, painter, target, source, aspectRatioMode)

    def __refresh(self):
        """refresh the legend"""
        self.clear()
        grp = self.createItems()
        self.setSceneRect(grp.boundingRect().adjusted(0,0,10,20))
        for item in grp.childItems():
            self.addItem(item);

    def maskUnits(self, flag):
        """
        Function to mask unit in the legend, used for probability map

        """
        self.__maskUnits = flag
        self.symbologyChanged.emit()

    def createItems(self):
        """returns a QGraphicsItemGroup that contains legend items"""
        grp = QGraphicsItemGroup()

        textHeight = QFontMetrics(QFont()).height()
        legendWidth = textHeight*20
        barWidth = textHeight
        barPosition = QPoint(0, 1.75*textHeight)
        headerPosition = QPoint(0,0)
        bottomSpace = 15
        text = QGraphicsTextItem(self.__title+(" ["+self.__units+"]" if not self.__maskUnits else ""))
        grp.addToGroup(text)
        text.setPos(headerPosition)

        if self.graduated():
            min_, max_ = (min([c[1] for c in self.__graduation]), max([c[2] for c in self.__graduation]))\
                    if len(self.__graduation) else (0,0)
            fmt = "%.2e"
            for i, (color, min_, max_) in enumerate(self.__graduation):
                pix = QPixmap(barWidth, textHeight*.8)
                pix.fill(color)
                img = QGraphicsPixmapItem(pix)
                img.setPos(barPosition+QPoint(0, int(i*textHeight)))
                grp.addToGroup(img)

                text = QGraphicsTextItem(fmt%(min_)+u" — "+fmt%(max_))
                text.setPos(barPosition+QPoint(barWidth+5, int((i-.25)*textHeight)))
                grp.addToGroup(text)

        else:
            values = list(self.values())

            barHeight = textHeight*len(values)*1.2
            tickSpacing = float(barHeight)/(len(values)-1)

            img = QGraphicsPixmapItem(QPixmap.fromImage(self.__colorRamp.scaled(barWidth, barHeight)))
            grp.addToGroup(img)
            img.setPos(barPosition)
            fmt = format_(self.__minValue, self.__maxValue)
            for i, value in enumerate(values):
                text = QGraphicsTextItem(fmt%(value))
                grp.addToGroup(text)
                text.setPos(barPosition+QPoint(barWidth+5, int(i*tickSpacing) - .75*textHeight))
                line = QGraphicsLineItem(QLineF(barPosition+QPoint(barWidth, int(i*tickSpacing)), barPosition+QPoint(barWidth+4, int(i*tickSpacing))))
                grp.addToGroup(line)
        return grp

    def setLogScale(self, trueOrFalse=True):
        """
        Setter function to set linear/log scale

        """
        self.__scale = "log" if trueOrFalse else "linear"
        self.__checkValues()
        self.__refresh()
        self.symbologyChanged.emit()

    def hasLogScale(self):
        """
        Getter function to set linear/log scale

        """
        return self.__scale == "log"

    def setTitle(self, text):
        """
        Setter function to set the legend title

        """
        assert text is not None
        self.__title = text
        self.__refresh()
        self.symbologyChanged.emit()

    def title(self):
        """
        Getter function to set the legend title

        """
        return self.__title

    def setUnits(self, text):
        """set the units to display in legend"""
        assert text is not None
        self.__units = text
        self.__refresh()
        self.symbologyChanged.emit()

    def units(self):
        return self.__units

    #def setMinMaxConverter(self, converter):
    #    """The converter provides the methods to() that
    #    convert the min and max values to .
    #    The converter also provides the displayText() method."""
    #    self.__unitsConverter = converter
    #    self.symbologyChanged.emit()

    def __checkValues(self):
        # in case of log scales, the min and max must be positive
        if self.__scale == "log":
            self.__minValue = max(self.__minValue, 1e-32)
            self.__maxValue = max(self.__maxValue, 1e-32)

    def setMinValue(self, value):
        """
        Setter function to update min value legend

        """
        self.__minValue = float(value)
        self.__checkValues()
        self.__refresh()
        self.symbologyChanged.emit()

    def setMaxValue(self, value):
        """
        Setter function to update max value legend

        """
        self.__maxValue = float(value)
        self.__checkValues()
        self.__refresh()
        self.symbologyChanged.emit()

    def setTransparencyPercent(self, value):
        """
        Setter function to update transparency values, from percent to float value

        """
        self.setTransparency(value/100.)

    def setTransparency(self, value):
        """
        Setter function to update transparency values

        """
        self.__transparency = float(value)
        self.__refresh()
        self.symbologyChanged.emit()

    def setColorRamp(self, rampImageFile):
        """
        Setter function to change the color ramp with a file path

        """
        self.__colorRampFile = rampImageFile
        self.__colorRamp = QImage(rampImageFile)
        self.__refresh()
        self.symbologyChanged.emit()

    def transparencyPercent(self):
        """
        Getter function for transparency value, from float value to percent

        """
        return int(self.__transparency*100)

    def minValue(self):
        """
        Getter function for min value

        """
        return self.__minValue

    def maxValue(self):
        """
        Getter function for min value

        """
        return self.__maxValue

    def colorRamp(self):
        """
        Getter function for colorRampFile value

        """
        return self.__colorRampFile

    def colorRampImg(self):
        """
        Getter function for colorRamp image value

        """
        return self.__colorRamp

    def _setUniformsLocation(self, shaders_):
        """Should be called once the shaders are compiled"""
        for name in ["transparency", "minValue", "maxValue", "tex", "logscale", "withNormals"]:
            self.__uniformLocations[name] = glGetUniformLocation(shaders_, name)

    def _setUniforms(self, glcontext, withNormals=False):
        """Should be called before the draw"""
        glUniform1f(self.__uniformLocations["transparency"], self.__transparency)
        glUniform1f(self.__uniformLocations["minValue"], self.__minValue)
        glUniform1f(self.__uniformLocations["maxValue"], self.__maxValue)
        glUniform1f(self.__uniformLocations["logscale"], int(self.hasLogScale()))
        glUniform1f(self.__uniformLocations["withNormals"], int(withNormals))

        # texture
        glEnable(GL_TEXTURE_2D)
        rot = QTransform()
        rot.rotate(180)
        self.tex = QOpenGLTexture(self.__colorRamp.transformed(rot))
        self.tex.setWrapMode(QOpenGLTexture.DirectionS, QOpenGLTexture.MirroredRepeat)
        self.tex.setWrapMode(QOpenGLTexture.DirectionT, QOpenGLTexture.MirroredRepeat)
        self.tex.setWrapMode(QOpenGLTexture.DirectionT, QOpenGLTexture.MirroredRepeat)
        self.tex.setMagnificationFilter(QOpenGLTexture.Linear)
        self.tex.setMinificationFilter(QOpenGLTexture.Linear)
        #glBindTexture(GL_TEXTURE_2D, glcontext.bindTexture(self.__colorRamp))
        #glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        #glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        #glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_MIRRORED_REPEAT)
        #glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_MIRRORED_REPEAT)
        self.tex.bind()

    def readXml(self, node, rwcontext):
        """
        Function to read mesh legend information from project

        """
        element = node.toElement()
        self.setTitle(element.attribute("title"))
        self.setMinValue(element.attribute("minValue"))
        self.setMaxValue(element.attribute("maxValue"))
        self.setTransparency(element.attribute("transparency"))
        self.setColorRamp(element.attribute("colorRampFile"))
        self.setUnits(element.attribute("units"))
        self.setLogScale(element.attribute("scale")=="log")
        graduation = []
        for c, min_, max_ in zip(*[iter(element.attribute("graduation").split())]*3):
            graduation.append((QColor(c), float(min_), float(max_)))
        self.setGraduation(graduation)
        self.toggleGraduation(bool(int(element.attribute("graduated"))))

        self.__refresh()
        return True

    def writeXml(self, node, doc, rwcontext):
        """
        Function to save mesh legend information in project
        """
        element = node.toElement()
        element.setAttribute("title", self.__title)
        element.setAttribute("minValue", str(self.__minValue))
        element.setAttribute("maxValue", str(self.__maxValue))
        element.setAttribute("transparency", str(self.__transparency))
        element.setAttribute("colorRampFile", self.__colorRampFile)
        element.setAttribute("units", self.__units)
        element.setAttribute("scale", self.__scale)
        element.setAttribute("graduated", self.__graduated)
        element.setAttribute("graduation", " ".join([g[0].name()+" "+str(g[1])+" "+str(g[2]) for g in self.__graduation]))
        return True

class GlMesh(QObject):
    """This class provides basic function to render results on a 2D mesh.
    The class must be instanciated in the main thread, but the draw function
    can be called in another thread.
    This class encapsulates the transformation between an extend and an image size.
    """
    def __init__(self, vtx, idx, legend):
        QObject.__init__(self)
        self.__vtx = numpy.require(vtx, numpy.float32, 'F')
        self.__idx = numpy.require(idx, numpy.int32, 'F')
        self.__pixBuf = None
        self.__legend = legend

        self.__legend.symbologyChanged.connect(self.__recompileNeeded)

        self.__colorPerElement = False
        self.__recompileShader = False

        self.__vtx[:,2] = 0

        if QApplication.instance().thread() != QThread.currentThread():
            raise RuntimeError("trying to use gl surface creation outside of main thread")

        self.__gl_surface = QOffscreenSurface()
        self.__gl_surface.create()

        self.__gl_ctx = QOpenGLContext()
        if not self.__gl_ctx.create():
            raise RuntimeError("unable to create gl context")


    def __recompileNeeded(self):
        """
        Set flag to recompile colorPixel

        """
        self.__recompileShader = True

    def setColorPerElement(self, flag):
        if self.__colorPerElement == flag:
            return # nothing to do
        self.__colorPerElement = flag
        if self.__colorPerElement:
            # we duplicate vertices
            idx = self.__idx
            self.__origVtx = self.__vtx
            self.__vtx = numpy.concatenate((
                    self.__origVtx[self.__idx[:,0]],
                    self.__origVtx[self.__idx[:,1]],
                    self.__origVtx[self.__idx[:,2]]))
            self.__origIdx = self.__idx
            nbElem = len(self.__idx)
            self.__idx = numpy.reshape(
                numpy.array([numpy.arange(nbElem),
                             numpy.arange(nbElem, 2*nbElem),
                             numpy.arange(2*nbElem, 3*nbElem)]),
                (3,-1)).transpose()
        else:
           self.__idx = self.__origIdx
           self.__vtx = self.__origVtx


    def colorPerElement(self):
        return self.__colorPerElement

    def __compileShaders(self):
        vertex_shader = shaders.compileShader("""
            varying float value;
            varying float w;
            varying vec3 normal;
            varying vec4 ecPos;
            void main()
            {
                ecPos = gl_ModelViewMatrix * gl_Vertex;
                normal = normalize(gl_NormalMatrix * gl_Normal);
                value = gl_MultiTexCoord0.st.x;
                w = value > 0.0 ? 1.0 : 0.0;
                gl_Position = ftransform();
            }
            """, GL_VERTEX_SHADER)

        fragment_shader = shaders.compileShader(
            self.__legend._fragmentShader(), GL_FRAGMENT_SHADER)

        self.__shaders = shaders.compileProgram(vertex_shader, fragment_shader)
        self.__legend._setUniformsLocation(self.__shaders)
        self.__recompileShader = False

    def __resize(self, roundupImageSize):
        # QOpenGLFramebufferObject size must be power of 2
        assert roundupImageSize == roundUpSize(roundupImageSize)

        fmt = QOpenGLFramebufferObjectFormat()

        self.__gl_ctx.makeCurrent(self.__gl_surface)
        self.__pixBuf = QOpenGLFramebufferObject(roundupImageSize, fmt)
        bound = self.__pixBuf.bind()
        # force viewport on entire buffer /!\
        glViewport(0,0, roundupImageSize.width(), roundupImageSize.height())
        self.__compileShaders()
        self.__gl_ctx.doneCurrent()

    def resetCoord(self, vtx):
        self.__vtx = numpy.require(vtx, numpy.float32, 'F')


    def image(self, values, imageSize, center, mapUnitsPerPixel, rotation=0):
        """Return the rendered image of a given size for values defined at each vertex
        or at each element depending on setColorPerElement.
        Values are normalized using valueRange = (minValue, maxValue).
        transparency is in the range [0,1]"""

        if QApplication.instance().thread() != QThread.currentThread():
            raise RuntimeError("trying to use gl draw calls in a thread")

        if not len(values):
            img = QImage(imageSize, QImage.Format_ARGB32)
            img.fill(Qt.transparent)
            return img

        roundupSz = roundUpSize(imageSize)

        if not self.__pixBuf \
                or roundupSz.width() != self.__pixBuf.size().width() \
                or roundupSz.height() != self.__pixBuf.size().height():
            self.__resize(roundupSz)

        val = numpy.require(values, numpy.float32) \
                if not isinstance(values, numpy.ndarray)\
                else values
        if self.__colorPerElement:
            val = numpy.concatenate((val,val,val))

        self.__gl_ctx.makeCurrent(self.__gl_surface)

        if self.__recompileShader:
            self.__compileShaders()

        glClearColor(0., 0., 0., 0.)

        glClear(GL_COLOR_BUFFER_BIT)

        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_TEXTURE_COORD_ARRAY)
        glEnable(GL_TEXTURE_2D)

        glShadeModel(GL_FLAT)
        glMatrixMode(GL_MODELVIEW)

        glLoadIdentity()

        # scale
        glScalef(2./(roundupSz.width()*mapUnitsPerPixel[0]),
                 2./(roundupSz.height()*mapUnitsPerPixel[1]),
                 1)
        # rotate
        glRotatef(-rotation, 0, 0, 1)

        ## translate
        glTranslatef(-center[0],
                     -center[1],
                     0)

        glUseProgram(self.__shaders)

        self.__legend._setUniforms(self.__gl_ctx)

        glVertexPointerf(self.__vtx)
        glTexCoordPointer(1, GL_FLOAT, 0, val)
        glDrawElementsui(GL_TRIANGLES, self.__idx)

        img = self.__pixBuf.toImage()
        self.__gl_ctx.doneCurrent()

        return img.copy( .5*(roundupSz.width()-imageSize.width()),
                         .5*(roundupSz.height()-imageSize.height()),
                         imageSize.width(), imageSize.height())



bgra_dtype = numpy.dtype({'b': (numpy.uint8, 0),
                          'g': (numpy.uint8, 1),
                          'r': (numpy.uint8, 2),
                          'a': (numpy.uint8, 3)})

def qimage2numpy(qimage, dtype = 'array'):
	"""Convert QImage to numpy.ndarray.  The dtype defaults to uint8
	for QImage.Format_Indexed8 or `bgra_dtype` (i.e. a record array)
	for 32bit color images.  You can pass a different dtype to use, or
	'array' to get a 3D uint8 array for color images."""
	result_shape = (qimage.height(), qimage.width())
	temp_shape = (qimage.height(),
				  qimage.bytesPerLine() * 8 // qimage.depth())
	if qimage.format() in (QImage.Format_ARGB32_Premultiplied,
						   QImage.Format_ARGB32,
						   QImage.Format_RGB32):
		if dtype == 'rec':
			dtype = bgra_dtype
		elif dtype == 'array':
			dtype = numpy.uint8
			result_shape += (4, )
			temp_shape += (4, )
	elif qimage.format() == QImage.Format_Indexed8:
		dtype = numpy.uint8
	else:
		raise ValueError("qimage2numpy only supports 32bit and 8bit images")
	# FIXME: raise error if alignment does not match
	buf = qimage.bits().asstring(qimage.byteCount())
	result = numpy.frombuffer(buf, dtype).reshape(temp_shape)
	if result_shape != temp_shape:
		result = result[:,:result_shape[1]]
	if qimage.format() == QImage.Format_RGB32 and dtype == numpy.uint8:
		result = result[...,:3]
	return result

def numpy2qimage(array):
	if numpy.ndim(array) == 2:
		return gray2qimage(array)
	elif numpy.ndim(array) == 3:
		return rgb2qimage(array)
	raise ValueError("can only convert 2D or 3D arrays")

def gray2qimage(gray):
	"""Convert the 2D numpy array `gray` into a 8-bit QImage with a gray
	colormap.  The first dimension represents the vertical image axis.

	ATTENTION: This QImage carries an attribute `ndimage` with a
	reference to the underlying numpy array that holds the data. On
	Windows, the conversion into a QPixmap does not copy the data, so
	that you have to take care that the QImage does not get garbage
	collected (otherwise PyQt will throw away the wrapper, effectively
	freeing the underlying memory - boom!)."""
	if len(gray.shape) != 2:
		raise ValueError("gray2QImage can only convert 2D arrays")

	gray = numpy.require(gray, numpy.uint8, 'C')

	h, w = gray.shape

	result = QImage(gray.data, w, h, QImage.Format_Indexed8)
	result.ndarray = gray
	for i in range(256):
		result.setColor(i, QColor(i, i, i).rgb())
	return result

def rgb2qimage(rgb):
	"""Convert the 3D numpy array `rgb` into a 32-bit QImage.  `rgb` must
	have three dimensions with the vertical, horizontal and RGB image axes.

	ATTENTION: This QImage carries an attribute `ndimage` with a
	reference to the underlying numpy array that holds the data. On
	Windows, the conversion into a QPixmap does not copy the data, so
	that you have to take care that the QImage does not get garbage
	collected (otherwise PyQt will throw away the wrapper, effectively
	freeing the underlying memory - boom!)."""
	if len(rgb.shape) != 3:
		raise ValueError("rgb2QImage can only convert 3D arrays")
	if rgb.shape[2] not in (3, 4):
		raise ValueError("rgb2QImage can expects the last dimension to contain exactly three (R,G,B) or four (R,G,B,A) channels")

	h, w, channels = rgb.shape

	# Qt expects 32bit BGRA data for color images:
	bgra = numpy.empty((h, w, 4), numpy.uint8, 'C')
	bgra[...,0] = rgb[...,2]
	bgra[...,1] = rgb[...,1]
	bgra[...,2] = rgb[...,0]
	if rgb.shape[2] == 3:
		bgra[...,3].fill(255)
		fmt = QImage.Format_RGB32
	else:
		bgra[...,3] = rgb[...,3]
		fmt = QImage.Format_ARGB32

	result = QImage(bgra.data, w, h, fmt)
	result.ndarray = bgra
	return result

if __name__ == "__main__":

    import sys

    app = QApplication(sys.argv)

    legend = ColorLegend()
    legend.setMinValue(.01)
    legend.setMaxValue(33)
    legend.setTransparencyPercent(50)
    mesh = GlMesh(((0,0,0),(1,0,0),(1,1,0),(1,2,0),(0,2,0),(0,1,0)),
            ((0,1,2),(0,2,5),(5,2,3),(5,3,4)), legend)
    img = mesh.image(
            (.01, .01, .5*33.01, 33, 33,  .5*33.01),
            QSize(800,600),
            (0,0),
            (8.0/800, 6.0/600)
            )
    img.save('/tmp/test_gl_mesh.png')
    img = QImage('/tmp/test_gl_mesh.png')
    ref = QImage(complete_filename('test_data/test_gl_mesh.png'))

    diff = qimage2numpy(img)[:,:,0:3] - qimage2numpy(ref)[:,:,0:3]
    numpy2qimage(diff).save("/tmp/diff.png")

    assert(numpy.linalg.norm(diff) < 200)

    legend.setLogScale(True)
    img = mesh.image(
            (.01, .01, .1, 33, 33, .1),
            QSize(800,600),
            (0,0),
            (8.0/800, 6.0/600)
            )
    img.save('/tmp/test_gl_mesh_log.png')

    #legend.setMinValue(.01)
    #legend.setMaxValue(33000)
    legend.image().save("/tmp/test_gl_mesh_legend.png")

    legend.setLogScale(False)
    mesh.setColorPerElement(True)
    img = mesh.image(
            (0, 10, 20, 30),
            QSize(800,600),
            (0,0),
            (8.0/800, 6.0/600)
            )
    img.save('/tmp/test_gl_flat.png')



