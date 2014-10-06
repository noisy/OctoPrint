# coding=utf-8
from __future__ import absolute_import

__author__ = "Gina Häußge <osd@foosel.net>"
__license__ = "GNU Affero General Public License http://www.gnu.org/licenses/agpl.html"
__copyright__ = "Copyright (C) 2014 The OctoPrint Project - Released under terms of the AGPLv3 License"

import logging
import os
import flask

import octoprint.plugin
import octoprint.util
import octoprint.slicing

default_settings = {
	"cura_engine": None,
	"default_profile": None
}
s = octoprint.plugin.plugin_settings("cura", defaults=default_settings)

from .profile import Profile

blueprint = flask.Blueprint("plugin.cura", __name__)

@blueprint.route("/import", methods=["POST"])
def importCuraProfile():
	import datetime
	import tempfile

	from octoprint.server import slicingManager

	input_name = "file"
	input_upload_name = input_name + "." + s.globalGet(["server", "uploads", "nameSuffix"])
	input_upload_path = input_name + "." + s.globalGet(["server", "uploads", "pathSuffix"])

	if input_upload_name in flask.request.values and input_upload_path in flask.request.values:
		filename = flask.request.values[input_upload_name]
		try:
			profile_dict = Profile.from_cura_ini(flask.request.values[input_upload_path])
		except Exception as e:
			return flask.make_response("Something went wrong while converting imported profile: {message}".format(e.message), 500)

	elif input_name in flask.request.files:
		temp_file = tempfile.NamedTemporaryFile("wb", delete=False)
		try:
			temp_file.close()
			upload = flask.request.files[input_name]
			upload.save(temp_file.name)
			profile_dict = Profile.from_cura_ini(temp_file.name)
		except Exception as e:
			return flask.make_response("Something went wrong while converting imported profile: {message}".format(e.message), 500)
		finally:
			os.remove(temp_file)

		filename = upload.filename

	else:
		return flask.make_response("No file included", 400)

	if profile_dict is None:
		return flask.make_response("Could not convert Cura profile", 400)

	name, _ = os.path.splitext(filename)

	# default values for name, display name and description
	profile_name = _sanitize_name(name)
	profile_display_name = name
	profile_description = "Imported from {filename} on {date}".format(filename=filename, date=octoprint.util.getFormattedDateTime(datetime.datetime.now()))
	profile_allow_overwrite = False

	# overrides
	if "name" in flask.request.values:
		profile_name = flask.request.values["name"]
	if "displayName" in flask.request.values:
		profile_display_name = flask.request.values["displayName"]
	if "description" in flask.request.values:
		profile_description = flask.request.values["description"]
	if "allowOverwrite" in flask.request.values:
		from octoprint.server.api import valid_boolean_trues
		profile_allow_overwrite = flask.request.values["allowOverwrite"] in valid_boolean_trues

	slicingManager.save_profile("cura",
	                            profile_name,
	                            profile_dict,
	                            allow_overwrite=profile_allow_overwrite,
	                            display_name=profile_display_name,
	                            description=profile_description)

	result = dict(
		resource=flask.url_for("api.slicingGetSlicerProfile", slicer="cura", name=profile_name, _external=True),
		displayName=profile_display_name,
		description=profile_description
	)
	r = flask.make_response(flask.jsonify(result), 201)
	r.headers["Location"] = result["resource"]
	return r


class CuraPlugin(octoprint.plugin.SlicerPlugin,
                 octoprint.plugin.SettingsPlugin,
                 octoprint.plugin.TemplatePlugin,
                 octoprint.plugin.AssetPlugin,
                 octoprint.plugin.BlueprintPlugin):

	def __init__(self):
		self._logger = logging.getLogger("octoprint.plugins." + __name__)

	##~~ BlueprintPlugin API

	def get_blueprint(self):
		global blueprint
		return blueprint

	##~~ AssetPlugin API

	def get_asset_folder(self):
		import os
		return os.path.join(os.path.dirname(os.path.realpath(__file__)), "static")

	def get_assets(self):
		return {
			"js": ["js/cura.js"],
			"less": ["less/cura.less"],
			"css": ["css/cura.css"]
		}

	##~~ SettingsPlugin API

	def on_settings_load(self):
		return dict(
			cura_engine=s.get(["cura_engine"]),
			default_profile=s.get(["default_profile"])
		)

	def on_settings_save(self, data):
		if "cura_engine" in data and data["cura_engine"]:
			s.set(["cura_engine"], data["cura_engine"])
		if "default_profile" in data and data["default_profile"]:
			s.set(["default_profile"], data["default_profile"])

	##~~ TemplatePlugin API

	def get_template_vars(self):
		return dict(
			_settings_menu_entry="Cura"
		)

	def get_template_folder(self):
		import os
		return os.path.join(os.path.dirname(os.path.realpath(__file__)), "templates")

	##~~ SlicerPlugin API

	def is_slicer_configured(self):
		cura_engine = s.get(["cura_engine"])
		return cura_engine is not None and os.path.exists(cura_engine)

	def get_slicer_type(self):
		return "cura"

	def get_slicer_name(self):
		return "CuraEngine"

	def get_slicer_default_profile(self):
		path = s.get(["default_profile"])
		if not path:
			path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "profiles", "default.profile.yaml")
		return self.get_slicer_profile(path)

	def get_slicer_profile(self, path):
		profile_dict = self._load_profile(path)

		display_name = None
		description = None
		if "_display_name" in profile_dict:
			display_name = profile_dict["_display_name"]
			del profile_dict["_display_name"]
		if "_description" in profile_dict:
			description = profile_dict["_description"]
			del profile_dict["_description"]

		return octoprint.slicing.SlicingProfile(self.get_slicer_type(), "unknown", profile_dict, display_name=display_name, description=description)

	def save_slicer_profile(self, path, profile, allow_overwrite=True, overrides=None):
		new_profile = Profile.merge_profile(profile.data, overrides=overrides)

		if profile.display_name is not None:
			new_profile["_display_name"] = profile.display_name
		if profile.description is not None:
			new_profile["_description"] = profile.description

		self._save_profile(path, new_profile, allow_overwrite=allow_overwrite)

	def do_slice(self, model_path, machinecode_path=None, profile_path=None):
		if not profile_path:
			profile_path = s.get(["default_profile"])
		if not machinecode_path:
			path, _ = os.path.splitext(model_path)
			machinecode_path = path + ".gco"

		engine_settings = self._convert_to_engine(profile_path)

		executable = s.get(["cura_engine"])
		if not executable:
			return False, "Path to CuraEngine is not configured "

		working_dir, _ = os.path.split(executable)
		args = ['"%s"' % executable, '-v', '-p']
		for k, v in engine_settings.items():
			args += ["-s", '"%s=%s"' % (k, str(v))]
		args += ['-o', '"%s"' % machinecode_path, '"%s"' % model_path]

		import sarge
		command = " ".join(args)
		self._logger.info("Running %r in %s" % (command, working_dir))
		try:
			p = sarge.run(command, cwd=working_dir)
			if p.returncode == 0:
				return True, None
			else:
				self._logger.warn("Could not slice via Cura, got return code %r" % p.returncode)
				return False, "Got returncode %r" % p.returncode
		except:
			self._logger.exception("Could not slice via Cura, got an unknown error")
			return False, "Unknown error, please consult the log file"


	def _load_profile(self, path):
		import yaml
		profile_dict = dict()
		with open(path, "r") as f:
			try:
				profile_dict = yaml.safe_load(f)
			except:
				raise IOError("Couldn't read profile from {path}".format(path=path))
		return profile_dict

	def _save_profile(self, path, profile, allow_overwrite=True):
		if not allow_overwrite and os.path.exists(path):
			raise IOError("Cannot overwrite {path}".format(path=path))

		import yaml
		with open(path, "wb") as f:
			yaml.safe_dump(profile, f, default_flow_style=False, indent="  ", allow_unicode=True)

	def _convert_to_engine(self, profile_path):
		profile = Profile(self._load_profile(profile_path))
		return profile.convert_to_engine()

def _sanitize_name(name):
	if name is None:
		return None

	if "/" in name or "\\" in name:
		raise ValueError("name must not contain / or \\")

	import string
	valid_chars = "-_.() {ascii}{digits}".format(ascii=string.ascii_letters, digits=string.digits)
	sanitized_name = ''.join(c for c in name if c in valid_chars)
	sanitized_name = sanitized_name.replace(" ", "_")
	return sanitized_name.lower()

__plugin_name__ = "cura"
__plugin_version__ = "0.1"
__plugin_implementations__ = [CuraPlugin()]