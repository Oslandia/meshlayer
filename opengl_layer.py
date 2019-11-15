# coding: utf-8
from OpenGL.GL import shaders

from qgis.core import QgsPluginLayerType, QgsMapLayerRenderer, QgsPluginLayer, QgsRectangle, QgsCoordinateReferenceSystem, QgsRenderContext

from PyQt5.QtCore import QMutex, QSize, QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QPainter, QImage

from .utilities import Timer

import os

class OpenGlLayerType(QgsPluginLayerType):
    def __init__(self, type_=None):
        QgsPluginLayerType.__init__(self, type_ or OpenGlLayer.LAYER_TYPE)
        #self.__dlg = None

    def createLayer(self):
        return OpenGlLayer()

    def showLayerProperties(self, layer):
        #self.__dlg = PropertyDialog(layer)
        return False

class OpenGlRenderer(QgsMapLayerRenderer):
    def __init__(self, layerId, rendererContext, layer):
        super(OpenGlRenderer, self).__init__(layerId)
        self.rendererContext = rendererContext
        self.layer = layer

    def render(self):
        return self.layer.draw(self.rendererContext)

class OpenGlLayer(QgsPluginLayer):
    """Base class to encapsulate the tricks to create OpenGL layers
    /!\ the layer is drwn in main thread due to current Qt limitations
    care must be taken not to stall the event loop while requesting
    a render job since since the rendering thread signal will not be
    passed to the main thread.

    Child class must implement the image method
    """

    LAYER_TYPE = "opengl_layer"

    __msg = pyqtSignal(str)
    __drawException = pyqtSignal(str)
    __imageChangeRequested = pyqtSignal()

    def __print(self, msg):
        # fix_print_with_import
        print(msg)

    def __raise(self, err):
        raise Exception(err)

    def __init__(self, type_=None, name=None):
        QgsPluginLayer.__init__(self, type_ if type_ is not None else OpenGlLayer.LAYER_TYPE, name)
        self.__imageChangedMutex = QMutex()
        self.__imageChangeRequested.connect(self.__drawInMainThread)
        self.__img = None
        self.__rendererContext = None
        self.__drawException.connect(self.__raise)
        self.__msg.connect(self.__print)
        self.setExtent(QgsRectangle(-1e9, -1e9, 1e9, 1e9))
        self.setCrs(QgsCoordinateReferenceSystem('EPSG:2154'))
        #self.__destCRS = None
        self.setValid(True)
        self.__timing = False

    def image(self, rendererContext, size):
        """This is the function that should be overwritten
        the rendererContext does not have a painter and an
        image must be returned instead
        """
        ext = rendererContext.extent()
        mapToPixel = rendererContext.mapToPixel()
        windowSize = QSize(
                int((ext.xMaximum()-ext.xMinimum())/mapToPixel.mapUnitsPerPixel()),
                int((ext.yMaximum()-ext.yMinimum())/mapToPixel.mapUnitsPerPixel()))
        img = QImage(windowSize, QImage.Format_ARGB32)
        painter = QPainter()
        painter.begin(img)
        painter.drawText(100, 100, "GlMesh.image default implementation")
        painter.end()
        img.save('/tmp/toto.png')
        # fix_print_with_import
        print("default image, we should not be here")
        return img

    def __drawInMainThread(self):
        self.__imageChangedMutex.lock()
        self.__img = self.image(self.__rendererContext, self.__size)
        self.__imageChangedMutex.unlock()

    def draw(self, rendererContext):
        """This function is called by the rendering thread.
        GlMesh must be created in the main thread."""
        timer = Timer() if self.__timing else None
        try:
            # /!\ DO NOT PRINT IN THREAD
            painter = rendererContext.painter()
            self.__imageChangedMutex.lock()
            self.__rendererContext = QgsRenderContext(rendererContext)
            self.__rendererContext.setPainter(None)
            self.__size = painter.viewport().size()
            self.__img = None
            self.__imageChangedMutex.unlock()
            if QApplication.instance().thread() != QThread.currentThread():
                self.__imageChangeRequested.emit()
                while not self.__img and not rendererContext.renderingStopped():
                    # active wait to avoid deadlocking if event loop is stopped
                    # this happens when a render job is cancellled
                    QThread.msleep(1)
                if rendererContext.renderingStopped():
                    self.__msg.emit("rendering stopped")

                if not rendererContext.renderingStopped():
                    painter.drawImage(0, 0, self.__img)
            else:
                self.__drawInMainThread()
                painter.drawImage(0, 0, self.__img)
            if self.__timing:
                self.__msg.emit(timer.reset("OpenGlLayer.draw"))
            return True
        except Exception as e:
            # since we are in a thread, we must re-raise the exception
            self.__drawException.emit(traceback.format_exc())
            return False

    def createMapRenderer(self, rendererContext):
        return OpenGlRenderer(self.id(), rendererContext, self)

    def setTransformContext(self, context):
        """
        Contains information about the context in which a coordinate transform is executed.
        """
        return