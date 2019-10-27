from qgis.core import QgsProcessing
from qgis.core import QgsProcessingAlgorithm
from qgis.core import QgsProcessingMultiStepFeedback
from qgis.core import QgsProcessingParameterVectorLayer
from qgis.core import QgsProcessingParameterField
from qgis.core import QgsProcessingParameterRasterDestination
import processing


class TrendSurface(QgsProcessingAlgorithm):

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer('perimeter', 'Perimeter', types=[QgsProcessing.TypeVectorLine], defaultValue=None))
        self.addParameter(QgsProcessingParameterVectorLayer('points', 'Points', types=[QgsProcessing.TypeVectorPoint], defaultValue=None))
        self.addParameter(QgsProcessingParameterField('zfield', 'Z field', type=QgsProcessingParameterField.Numeric, parentLayerParameterName='points', allowMultiple=False, defaultValue=None))
        self.addParameter(QgsProcessingParameterRasterDestination('Idw', 'IDW', createByDefault=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterRasterDestination('Trend', 'TREND', createByDefault=True, defaultValue=None))

    def processAlgorithm(self, parameters, context, model_feedback):
        # Use a multi-step feedback, so that individual child algorithm progress reports are adjusted for the
        # overall progress through the model
        feedback = QgsProcessingMultiStepFeedback(9, model_feedback)
        results = {}
        outputs = {}

        # Convert lines to polygons
        # The polygon is needed for buffer layer to define  output extent of Inverse-Distance-Weighted Interpolation; 
        # IDW interpolation must extent beyond the perimeter points in order to be sampled for Z0 trend plane interpolation
        alg_params = {
            'LINES': parameters['perimeter'],
            'POLYGONS': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ConvertLinesToPolygons'] = processing.run('saga:convertlinestopolygons', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}

        # Convert lines to points
        # Points will be used to sample the IDW surface at the perimeter of the flake.  Point spacing interval is 0.2mm.
        alg_params = {
            'ADD         ': True,
            'DIST': 0.2,
            'LINES': parameters['perimeter'],
            'POINTS': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ConvertLinesToPoints'] = processing.run('saga:convertlinestopoints', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(2)
        if feedback.isCanceled():
            return {}

        # Buffer
        # Needed to define  output extent of Inverse-Distance-Weighted Interpolation; 
        # Interpolation must extent beyond the perimeter points in order to be sampled for Z0 trend plane interpolation
        alg_params = {
            'DISSOLVE': False,
            'DISTANCE': 0.1,
            'END_CAP_STYLE': 0,
            'INPUT': outputs['ConvertLinesToPolygons']['POLYGONS'],
            'JOIN_STYLE': 0,
            'MITER_LIMIT': 2,
            'SEGMENTS': 5,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['Buffer'] = processing.run('native:buffer', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(3)
        if feedback.isCanceled():
            return {}

        # Inverse distance weighted interpolation
        # IDW: interpolate flake surface.  IDW used with power = 1.5, resolution = 0.05mm.  Precision is good, and outlying points are negated.
        alg_params = {
            'DW_BANDWIDTH': 1,
            'DW_IDW_OFFSET': False,
            'DW_IDW_POWER': 1.5,
            'DW_WEIGHTING': 1,
            'FIELD': parameters['zfield'],
            'SEARCH_DIRECTION': 0,
            'SEARCH_POINTS_ALL': 0,
            'SEARCH_POINTS_MAX': 20,
            'SEARCH_POINTS_MIN': -1,
            'SEARCH_RADIUS': 1000,
            'SEARCH_RANGE': 0,
            'SHAPES': parameters['points'],
            'TARGET_DEFINITION': 0,
            'TARGET_TEMPLATE': None,
            'TARGET_USER_FITS': 0,
            'TARGET_USER_SIZE': 0.05,
            'TARGET_USER_XMIN TARGET_USER_XMAX TARGET_USER_YMIN TARGET_USER_YMAX': outputs['Buffer']['OUTPUT'],
            'TARGET_OUT_GRID': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['InverseDistanceWeightedInterpolation'] = processing.run('saga:inversedistanceweightedinterpolation', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(4)
        if feedback.isCanceled():
            return {}

        # Translate (convert format)
        # SAGA raster output in QGIS 3.X defaults to SGRID and must be changed to TIF in order to be used and exported successfully. It's a pain in the ass and I wish I could fix it.
        alg_params = {
            'COPY_SUBDATASETS': False,
            'DATA_TYPE': 0,
            'INPUT': outputs['InverseDistanceWeightedInterpolation']['TARGET_OUT_GRID'],
            'NODATA': None,
            'OPTIONS': '',
            'TARGET_CRS': None,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['TranslateConvertFormat'] = processing.run('gdal:translate', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(5)
        if feedback.isCanceled():
            return {}

        # Add raster values to points
        # Points created along perimeter line sample Z values from IDW surface.
        alg_params = {
            'GRIDS': outputs['TranslateConvertFormat']['OUTPUT'],
            'RESAMPLING': 0,
            'SHAPES': outputs['ConvertLinesToPoints']['POINTS'],
            'RESULT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['AddRasterValuesToPoints'] = processing.run('saga:addrastervaluestopoints', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(6)
        if feedback.isCanceled():
            return {}

        # Clip raster with polygon
        # Clip the IDW surface and export it.  Exporting makes it easy to check that the IDW surface was currectly interpolated. (Compare with the real artifact)
        alg_params = {
            'INPUT': outputs['InverseDistanceWeightedInterpolation']['TARGET_OUT_GRID'],
            'POLYGONS': outputs['ConvertLinesToPolygons']['POLYGONS'],
            'OUTPUT': parameters['Idw']
        }
        outputs['ClipRasterWithPolygon'] = processing.run('saga:cliprasterwithpolygon', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        results['Idw'] = outputs['ClipRasterWithPolygon']['OUTPUT']

        feedback.setCurrentStep(7)
        if feedback.isCanceled():
            return {}

        # Natural neighbour
        # Z0 "trend" surface is interpolated between perimeter points.
        alg_params = {
            'FIELD': parameters['zfield'],
            'METHOD': 0,
            'SHAPES': outputs['AddRasterValuesToPoints']['RESULT'],
            'TARGET_TEMPLATE': None,
            'TARGET_USER_FITS': 0,
            'TARGET_USER_SIZE': 0.05,
            'TARGET_USER_XMIN TARGET_USER_XMAX TARGET_USER_YMIN TARGET_USER_YMAX': None,
            'WEIGHT': 0,
            'TARGET_OUT_GRID': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['NaturalNeighbour'] = processing.run('saga:naturalneighbour', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(8)
        if feedback.isCanceled():
            return {}

        # Clip raster with polygon
        # Natural Neighbour surface (Z0 "trend" surface) is clipped and exported to "Trend".
        alg_params = {
            'INPUT': outputs['NaturalNeighbour']['TARGET_OUT_GRID'],
            'POLYGONS': outputs['ConvertLinesToPolygons']['POLYGONS'],
            'OUTPUT': parameters['Trend']
        }
        outputs['ClipRasterWithPolygon'] = processing.run('saga:cliprasterwithpolygon', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        results['Trend'] = outputs['ClipRasterWithPolygon']['OUTPUT']
        return results

    def name(self):
        return 'trend surface'

    def displayName(self):
        return 'trend surface'

    def group(self):
        return 'lithic analysis'

    def groupId(self):
        return 'lithic analysis'

    def createInstance(self):
        return TrendSurface()
