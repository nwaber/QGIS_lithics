from qgis.core import QgsProcessing
from qgis.core import QgsProcessingAlgorithm
from qgis.core import QgsProcessingMultiStepFeedback
from qgis.core import QgsProcessingParameterNumber
from qgis.core import QgsProcessingParameterRasterLayer
from qgis.core import QgsProcessingParameterVectorLayer
from qgis.core import QgsProcessingParameterRasterDestination
import processing


class EdgeFromProjection04(QgsProcessingAlgorithm):

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterNumber('expectedflakescarlengthmm', 'Expected flake scar length (mm)', type=QgsProcessingParameterNumber.Double, minValue=0, maxValue=25, defaultValue=0.8))
        self.addParameter(QgsProcessingParameterRasterLayer('lithicsurface', 'Worn dorsal surface', defaultValue=None))
        self.addParameter(QgsProcessingParameterVectorLayer('perimeter', 'Perimeter', types=[QgsProcessing.TypeVectorLine], defaultValue=None))
        self.addParameter(QgsProcessingParameterVectorLayer('platformspolygon', 'Platform(s) [polygon]', types=[QgsProcessing.TypeVectorPolygon], defaultValue=None))
        self.addParameter(QgsProcessingParameterVectorLayer('projectedpoints', 'Projected points', types=[QgsProcessing.TypeVectorPoint], defaultValue=None))
        self.addParameter(QgsProcessingParameterRasterLayer('wornventralsurface', 'Worn ventral surface', defaultValue=None))
        self.addParameter(QgsProcessingParameterRasterDestination('DorsalReconstruction', 'DORSAL RECONSTRUCTION', createByDefault=True, defaultValue=None))
        self.addParameter(QgsProcessingParameterRasterDestination('VentralReconstruction', 'VENTRAL RECONSTRUCTION', createByDefault=True, defaultValue=None))

    def processAlgorithm(self, parameters, context, model_feedback):
        # Use a multi-step feedback, so that individual child algorithm progress reports are adjusted for the
        # overall progress through the model
        feedback = QgsProcessingMultiStepFeedback(42, model_feedback)
        results = {}
        outputs = {}

        # Translate (convert format) DUMMY VENTRAL
        # This is to change the name of the input layer to the default layer name 'OUTPUT'.  QGIS scripts involving Refactor Fields and Field Calculator need predictable layer names.
        alg_params = {
            'COPY_SUBDATASETS': False,
            'DATA_TYPE': 0,
            'INPUT': parameters['wornventralsurface'],
            'NODATA': None,
            'OPTIONS': '',
            'TARGET_CRS': None,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['TranslateConvertFormatDummyVentral'] = processing.run('gdal:translate', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}

        # Centroids
        # Creates the PERIM centroid for hub lines.
        alg_params = {
            'ALL_PARTS': False,
            'INPUT': parameters['perimeter'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['Centroids'] = processing.run('native:centroids', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(2)
        if feedback.isCanceled():
            return {}

        # Convert lines to polygons PERIM
        # Converts the perimeter line to a polygon so it can merge with the cluster-based perimeter polygon
        alg_params = {
            'LINES': parameters['perimeter'],
            'POLYGONS': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ConvertLinesToPolygonsPerim'] = processing.run('saga:convertlinestopolygons', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(3)
        if feedback.isCanceled():
            return {}

        # Heatmap (Kernel Density Estimation)
        # Quantify density of extrapolated points
        alg_params = {
            'DECAY': 0,
            'INPUT': parameters['projectedpoints'],
            'KERNEL': 0,
            'OUTPUT_VALUE': 0,
            'PIXEL_SIZE': 0.1,
            'RADIUS': 0.5,
            'RADIUS_FIELD': None,
            'WEIGHT_FIELD': None,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['HeatmapKernelDensityEstimation'] = processing.run('qgis:heatmapkerneldensityestimation', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(4)
        if feedback.isCanceled():
            return {}

        # Points along geometry PERIM
        # Creates points along the perimeter for sections not recorded by the cluster-generated points (i.e. proximal/distal ends)
        alg_params = {
            'DISTANCE': 0.2,
            'END_OFFSET': 0,
            'INPUT': parameters['perimeter'],
            'START_OFFSET': 0,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['PointsAlongGeometryPerim'] = processing.run('qgis:pointsalonglines', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(5)
        if feedback.isCanceled():
            return {}

        # Translate DUMMY DEM
        # Changes DEM name, as above
        alg_params = {
            'COPY_SUBDATASETS': False,
            'DATA_TYPE': 0,
            'INPUT': parameters['lithicsurface'],
            'NODATA': None,
            'OPTIONS': '',
            'TARGET_CRS': 'ProjectCrs',
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['TranslateDummyDem'] = processing.run('gdal:translate', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(6)
        if feedback.isCanceled():
            return {}

        # Local minima and maxima
        # Finds the peak densities in the heatmap
        alg_params = {
            'GRID': outputs['HeatmapKernelDensityEstimation']['OUTPUT'],
            'MAXIMA': QgsProcessing.TEMPORARY_OUTPUT,
            'MINIMA': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['LocalMinimaAndMaxima'] = processing.run('saga:localminimaandmaxima', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(7)
        if feedback.isCanceled():
            return {}

        # Extract by expression
        # Extracts density peaks that are above the mean density value.
        alg_params = {
            'EXPRESSION': '\"Z\"  > mean(\"Z\")',
            'INPUT': outputs['LocalMinimaAndMaxima']['MAXIMA'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ExtractByExpression'] = processing.run('native:extractbyexpression', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(8)
        if feedback.isCanceled():
            return {}

        # Field calculator DUMMY ID
        # Adds a dummy ID column to the density points layer for hub line generation
        alg_params = {
            'FIELD_LENGTH': 10,
            'FIELD_NAME': 'ID',
            'FIELD_PRECISION': 3,
            'FIELD_TYPE': 0,
            'FORMULA': '1',
            'INPUT': outputs['ExtractByExpression']['OUTPUT'],
            'NEW_FIELD': True,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['FieldCalculatorDummyId'] = processing.run('qgis:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(9)
        if feedback.isCanceled():
            return {}

        # Join by lines (hub lines)
        # Connects centroid to density points by hub lines.  
        alg_params = {
            'ANTIMERIDIAN_SPLIT': False,
            'GEODESIC': False,
            'GEODESIC_DISTANCE': 1000,
            'HUBS': outputs['Centroids']['OUTPUT'],
            'HUB_FIELD': 'local_idx',
            'HUB_FIELDS': None,
            'SPOKES': outputs['FieldCalculatorDummyId']['OUTPUT'],
            'SPOKE_FIELD': 'ID',
            'SPOKE_FIELDS': None,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['JoinByLinesHubLines'] = processing.run('native:hublines', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(10)
        if feedback.isCanceled():
            return {}

        # Field calculator AZIMUTH
        # Gives points azimuth value so the edge line is drawn in the correct order.
        alg_params = {
            'FIELD_LENGTH': 10,
            'FIELD_NAME': 'AZIMUTH',
            'FIELD_PRECISION': 3,
            'FIELD_TYPE': 0,
            'FORMULA': 'azimuth(start_point($geometry),end_point($geometry))',
            'INPUT': outputs['JoinByLinesHubLines']['OUTPUT'],
            'NEW_FIELD': True,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['FieldCalculatorAzimuth'] = processing.run('qgis:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(11)
        if feedback.isCanceled():
            return {}

        # Extract vertices
        alg_params = {
            'INPUT': outputs['FieldCalculatorAzimuth']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ExtractVertices'] = processing.run('native:extractvertices', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(12)
        if feedback.isCanceled():
            return {}

        # Extract by location
        # Extracts aximuth line vertices where they patch the density points.
        alg_params = {
            'INPUT': outputs['ExtractVertices']['OUTPUT'],
            'INTERSECT': outputs['ExtractByExpression']['OUTPUT'],
            'PREDICATE': 0,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ExtractByLocation'] = processing.run('native:extractbylocation', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(13)
        if feedback.isCanceled():
            return {}

        # Field calculator DUMMY Z
        # Adds 0 Z value to ordered density points.
        alg_params = {
            'FIELD_LENGTH': 10,
            'FIELD_NAME': 'Z',
            'FIELD_PRECISION': 3,
            'FIELD_TYPE': 0,
            'FORMULA': '0',
            'INPUT': outputs['ExtractByLocation']['OUTPUT'],
            'NEW_FIELD': False,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['FieldCalculatorDummyZ'] = processing.run('qgis:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(14)
        if feedback.isCanceled():
            return {}

        # Points to path
        # Draws edge line along the density points, in azimuth order.
        alg_params = {
            'DATE_FORMAT': '',
            'GROUP_FIELD': None,
            'INPUT': outputs['FieldCalculatorDummyZ']['OUTPUT'],
            'ORDER_FIELD': 'AZIMUTH',
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['PointsToPath'] = processing.run('qgis:pointstopath', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(15)
        if feedback.isCanceled():
            return {}

        # Explode lines
        # I forget why this happens, but it's needed.
        alg_params = {
            'INPUT': outputs['PointsToPath']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ExplodeLines'] = processing.run('native:explodelines', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(16)
        if feedback.isCanceled():
            return {}

        # Convert lines to polygons NEWEDGE
        # Creates a polygon from the newly drawn edge line.
        alg_params = {
            'LINES': outputs['PointsToPath']['OUTPUT'],
            'POLYGONS': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ConvertLinesToPolygonsNewedge'] = processing.run('saga:convertlinestopolygons', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(17)
        if feedback.isCanceled():
            return {}

        # Extract by expression DROP CROSSLINES
        # This relates to the Explode Lines, but it was a while ago.
        alg_params = {
            'EXPRESSION': '$length < maximum($length)',
            'INPUT': outputs['ExplodeLines']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ExtractByExpressionDropCrosslines'] = processing.run('native:extractbyexpression', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(18)
        if feedback.isCanceled():
            return {}

        # Difference PERIM PTS
        # Isolates points generated along the worn perimeter that fall outside the new perimeter polygon.
        alg_params = {
            'INPUT': outputs['PointsAlongGeometryPerim']['OUTPUT'],
            'OVERLAY': outputs['ConvertLinesToPolygonsNewedge']['POLYGONS'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['DifferencePerimPts'] = processing.run('native:difference', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(19)
        if feedback.isCanceled():
            return {}

        # Points along geometry
        # Create points along the new edge lines
        alg_params = {
            'DISTANCE': 0.2,
            'END_OFFSET': 0,
            'INPUT': outputs['ExtractByExpressionDropCrosslines']['OUTPUT'],
            'START_OFFSET': 0,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['PointsAlongGeometry'] = processing.run('qgis:pointsalonglines', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(20)
        if feedback.isCanceled():
            return {}

        # Field calculator DUMMY Z
        # Adds dummy Z value for interpolation.  I feel like it might be redundant, but IF IT AIN'T BROKE...
        alg_params = {
            'FIELD_LENGTH': 10,
            'FIELD_NAME': 'Z',
            'FIELD_PRECISION': 3,
            'FIELD_TYPE': 0,
            'FORMULA': '0',
            'INPUT': outputs['PointsAlongGeometry']['OUTPUT'],
            'NEW_FIELD': False,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['FieldCalculatorDummyZ'] = processing.run('qgis:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(21)
        if feedback.isCanceled():
            return {}

        # Field calculator PERIM PTS
        # Adds another dummy Z value.
        alg_params = {
            'FIELD_LENGTH': 10,
            'FIELD_NAME': 'Z',
            'FIELD_PRECISION': 3,
            'FIELD_TYPE': 0,
            'FORMULA': '0',
            'INPUT': outputs['DifferencePerimPts']['OUTPUT'],
            'NEW_FIELD': True,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['FieldCalculatorPerimPts'] = processing.run('qgis:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(22)
        if feedback.isCanceled():
            return {}

        # Difference PLATFORMS
        # Polygons that mark striking platform and/or distal edge cut out Z=0 points
        alg_params = {
            'INPUT': outputs['FieldCalculatorDummyZ']['OUTPUT'],
            'OVERLAY': parameters['platformspolygon'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['DifferencePlatforms'] = processing.run('native:difference', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(23)
        if feedback.isCanceled():
            return {}

        # Buffer
        alg_params = {
            'DISSOLVE': True,
            'DISTANCE': parameters['expectedflakescarlengthmm'],
            'END_CAP_STYLE': 0,
            'INPUT': outputs['DifferencePlatforms']['OUTPUT'],
            'JOIN_STYLE': 0,
            'MITER_LIMIT': 2,
            'SEGMENTS': 5,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['Buffer'] = processing.run('native:buffer', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(24)
        if feedback.isCanceled():
            return {}

        # Difference PTS OUTSIDE PERIM
        alg_params = {
            'INPUT': outputs['DifferencePlatforms']['OUTPUT'],
            'OVERLAY': outputs['ConvertLinesToPolygonsPerim']['POLYGONS'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['DifferencePtsOutsidePerim'] = processing.run('native:difference', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(25)
        if feedback.isCanceled():
            return {}

        # Difference SAMPLE v PROJECTED
        alg_params = {
            'INPUT': outputs['ConvertLinesToPolygonsPerim']['POLYGONS'],
            'OVERLAY': outputs['Buffer']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['DifferenceSampleVProjected'] = processing.run('native:difference', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(26)
        if feedback.isCanceled():
            return {}

        # Refactor fields PERIM PTS
        alg_params = {
            'FIELDS_MAPPING': [{'expression': '"Z"', 'length': 10, 'name': 'Z', 'precision': 3, 'type': 6}],
            'INPUT': outputs['FieldCalculatorPerimPts']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['RefactorFieldsPerimPts'] = processing.run('qgis:refactorfields', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(27)
        if feedback.isCanceled():
            return {}

        # Refactor fields EDGE
        alg_params = {
            'FIELDS_MAPPING': [{'expression': '"Z"', 'length': 10, 'name': 'Z', 'precision': 3, 'type': 6}],
            'INPUT': outputs['DifferencePtsOutsidePerim']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['RefactorFieldsEdge'] = processing.run('qgis:refactorfields', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(28)
        if feedback.isCanceled():
            return {}

        # Clip raster by mask layer DORSAL
        alg_params = {
            'ALPHA_BAND': False,
            'CROP_TO_CUTLINE': True,
            'DATA_TYPE': 0,
            'INPUT': outputs['TranslateDummyDem']['OUTPUT'],
            'KEEP_RESOLUTION': False,
            'MASK': outputs['DifferenceSampleVProjected']['OUTPUT'],
            'MULTITHREADING': False,
            'NODATA': None,
            'OPTIONS': '',
            'TARGET_EXTENT': None,
            'TARGET_EXTENT_CRS': None,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ClipRasterByMaskLayerDorsal'] = processing.run('gdal:cliprasterbymasklayer', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(29)
        if feedback.isCanceled():
            return {}

        # Clip raster by mask layer VENTRAL
        alg_params = {
            'ALPHA_BAND': False,
            'CROP_TO_CUTLINE': True,
            'DATA_TYPE': 0,
            'INPUT': outputs['TranslateConvertFormatDummyVentral']['OUTPUT'],
            'KEEP_RESOLUTION': False,
            'MASK': outputs['DifferenceSampleVProjected']['OUTPUT'],
            'MULTITHREADING': False,
            'NODATA': None,
            'OPTIONS': '',
            'TARGET_EXTENT': None,
            'TARGET_EXTENT_CRS': None,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ClipRasterByMaskLayerVentral'] = processing.run('gdal:cliprasterbymasklayer', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(30)
        if feedback.isCanceled():
            return {}

        # Raster values to points VENTRAL
        alg_params = {
            'GRIDS': outputs['ClipRasterByMaskLayerVentral']['OUTPUT'],
            'NODATA': True,
            'POLYGONS': None,
            'TYPE': 0,
            'SHAPES': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['RasterValuesToPointsVentral'] = processing.run('saga:rastervaluestopoints', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(31)
        if feedback.isCanceled():
            return {}

        # Raster values to points DORSAL
        alg_params = {
            'GRIDS': outputs['ClipRasterByMaskLayerDorsal']['OUTPUT'],
            'NODATA': True,
            'POLYGONS': None,
            'TYPE': 0,
            'SHAPES': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['RasterValuesToPointsDorsal'] = processing.run('saga:rastervaluestopoints', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(32)
        if feedback.isCanceled():
            return {}

        # Refactor fields DORSAL
        alg_params = {
            'FIELDS_MAPPING': [{'expression': '"OUTPUT"', 'length': 18, 'name': 'Z', 'precision': 10, 'type': 6}],
            'INPUT': outputs['RasterValuesToPointsDorsal']['SHAPES'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['RefactorFieldsDorsal'] = processing.run('qgis:refactorfields', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(33)
        if feedback.isCanceled():
            return {}

        # Refactor fields VENTRAL
        alg_params = {
            'FIELDS_MAPPING': [{'expression': '"OUTPUT"', 'length': 18, 'name': 'Z', 'precision': 10, 'type': 6}],
            'INPUT': outputs['RasterValuesToPointsVentral']['SHAPES'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['RefactorFieldsVentral'] = processing.run('qgis:refactorfields', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(34)
        if feedback.isCanceled():
            return {}

        # Merge vector layers VENTRAL
        alg_params = {
            'CRS': None,
            'LAYERS': [outputs['RefactorFieldsEdge']['OUTPUT'],outputs['RefactorFieldsPerimPts']['OUTPUT'],outputs['RefactorFieldsVentral']['OUTPUT']],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['MergeVectorLayersVentral'] = processing.run('native:mergevectorlayers', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(35)
        if feedback.isCanceled():
            return {}

        # Concave hull (alpha shapes) VENTRAL
        alg_params = {
            'ALPHA': 0.275,
            'HOLES': False,
            'INPUT': outputs['MergeVectorLayersVentral']['OUTPUT'],
            'NO_MULTIGEOMETRY': False,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ConcaveHullAlphaShapesVentral'] = processing.run('qgis:concavehull', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(36)
        if feedback.isCanceled():
            return {}

        # Merge vector layers DORSAL
        alg_params = {
            'CRS': None,
            'LAYERS': [outputs['RefactorFieldsDorsal']['OUTPUT'],outputs['RefactorFieldsEdge']['OUTPUT'],outputs['RefactorFieldsPerimPts']['OUTPUT']],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['MergeVectorLayersDorsal'] = processing.run('native:mergevectorlayers', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(37)
        if feedback.isCanceled():
            return {}

        # Grid (Linear) DORSAL
        alg_params = {
            'DATA_TYPE': 5,
            'INPUT': outputs['MergeVectorLayersDorsal']['OUTPUT'],
            'NODATA': 0,
            'OPTIONS': '',
            'RADIUS': -1,
            'Z_FIELD': 'Z',
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['GridLinearDorsal'] = processing.run('gdal:gridlinear', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(38)
        if feedback.isCanceled():
            return {}

        # Concave hull (alpha shapes) DORSAL
        alg_params = {
            'ALPHA': 0.275,
            'HOLES': False,
            'INPUT': outputs['MergeVectorLayersDorsal']['OUTPUT'],
            'NO_MULTIGEOMETRY': False,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ConcaveHullAlphaShapesDorsal'] = processing.run('qgis:concavehull', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(39)
        if feedback.isCanceled():
            return {}

        # Grid (Linear) VENTRAL
        alg_params = {
            'DATA_TYPE': 5,
            'INPUT': outputs['MergeVectorLayersVentral']['OUTPUT'],
            'NODATA': 0,
            'OPTIONS': '',
            'RADIUS': -1,
            'Z_FIELD': 'Z',
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['GridLinearVentral'] = processing.run('gdal:gridlinear', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(40)
        if feedback.isCanceled():
            return {}

        # Clip raster by mask layer VENTRAL OUTPUT
        alg_params = {
            'ALPHA_BAND': False,
            'CROP_TO_CUTLINE': True,
            'DATA_TYPE': 0,
            'INPUT': outputs['GridLinearVentral']['OUTPUT'],
            'KEEP_RESOLUTION': False,
            'MASK': outputs['ConcaveHullAlphaShapesVentral']['OUTPUT'],
            'MULTITHREADING': False,
            'NODATA': None,
            'OPTIONS': '',
            'TARGET_EXTENT': None,
            'TARGET_EXTENT_CRS': None,
            'OUTPUT': parameters['VentralReconstruction']
        }
        outputs['ClipRasterByMaskLayerVentralOutput'] = processing.run('gdal:cliprasterbymasklayer', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        results['VentralReconstruction'] = outputs['ClipRasterByMaskLayerVentralOutput']['OUTPUT']

        feedback.setCurrentStep(41)
        if feedback.isCanceled():
            return {}

        # Clip raster by mask layer DORSAL OUTPUT
        alg_params = {
            'ALPHA_BAND': False,
            'CROP_TO_CUTLINE': True,
            'DATA_TYPE': 0,
            'INPUT': outputs['GridLinearDorsal']['OUTPUT'],
            'KEEP_RESOLUTION': False,
            'MASK': outputs['ConcaveHullAlphaShapesDorsal']['OUTPUT'],
            'MULTITHREADING': False,
            'NODATA': None,
            'OPTIONS': '',
            'TARGET_EXTENT': None,
            'TARGET_EXTENT_CRS': None,
            'OUTPUT': parameters['DorsalReconstruction']
        }
        outputs['ClipRasterByMaskLayerDorsalOutput'] = processing.run('gdal:cliprasterbymasklayer', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        results['DorsalReconstruction'] = outputs['ClipRasterByMaskLayerDorsalOutput']['OUTPUT']
        return results

    def name(self):
        return 'edge from projection 0.4'

    def displayName(self):
        return 'edge from projection 0.4'

    def group(self):
        return 'lithics IN PROGRESS'

    def groupId(self):
        return 'lithics IN PROGRESS'

    def createInstance(self):
        return EdgeFromProjection04()
