FILES=\
    metadata.txt\
    LICENSE \
    images

package: ${FILES} $(wildcard *.py) $(wildcard *.ui)
	rm -rf meshlayer
	mkdir meshlayer
	cp -r $^ meshlayer/
	rm -f meshlayer.zip
	zip -r meshlayer.zip meshlayer
	rm -r meshlayer

install: package
	rm -rf ${HOME}/.qgis2/python/plugins/meshlayer
	unzip -o meshlayer.zip -d ${HOME}/.qgis2/python/plugins

test:
	python gl_mesh.py
	#python zns_scene.py


clean:
	find . -name '*.pyc' | xargs rm -f
	rm -f meshlayer.zip
