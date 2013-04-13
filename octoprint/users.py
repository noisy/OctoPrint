# coding=utf-8
__author__ = "Gina Häußge <osd@foosel.net>"
__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'

from flask.ext.login import UserMixin
import hashlib
import os
import yaml

from octoprint.settings import settings

class UserManager(object):
	valid_roles = ["user", "admin"]

	@staticmethod
	def createPasswordHash(password):
		return hashlib.sha512(password + "mvBUTvwzBzD3yPwvnJ4E4tXNf3CGJvvW").hexdigest()

	def addUser(self, username, password, active, roles):
		pass

	def changeUserActivation(self, username, active):
		pass

	def changeUserRoles(self, username, roles):
		pass

	def addRolesToUser(self, username, roles):
		pass

	def removeRolesFromUser(self, username, roles):
		pass

	def changeUserPassword(self, username, password):
		pass

	def removeUser(self, username):
		pass

	def findUser(self, username=None):
		return None

	def getAllUsers(self):
		return []

##~~ FilebasedUserManager, takes available users from users.yaml file

class FilebasedUserManager(UserManager):
	def __init__(self):
		UserManager.__init__(self)

		userfile = settings().get(["accessControl", "userfile"])
		if userfile is None:
			userfile = os.path.join(settings().settings_dir, "users.yaml")
		self._userfile = userfile
		self._users = {}
		self._dirty = False

		self._load()

	def _load(self):
		if os.path.exists(self._userfile) and os.path.isfile(self._userfile):
			with open(self._userfile, "r") as f:
				data = yaml.safe_load(f)
				for name in data.keys():
					attributes = data[name]
					self._users[name] = User(name, attributes["password"], attributes["active"], attributes["roles"])
		else:
			self._users["admin"] = User("admin", "7557160613d5258f883014a7c3c0428de53040fc152b1791f1cc04a62b428c0c2a9c46ed330cdce9689353ab7a5352ba2b2ceb459b96e9c8ed7d0cb0b2c0c076", True, ["user", "admin"])

	def _save(self, force=False):
		if not self._dirty and not force:
			return

		data = {}
		for name in self._users.keys():
			user = self._users[name]
			data[name] = {
				"password": user._passwordHash,
				"active": user._active,
				"roles": user._roles
			}

		with open(self._userfile, "wb") as f:
			yaml.safe_dump(data, f, default_flow_style=False, indent="    ", allow_unicode=True)
			self._dirty = False
		self._load()

	def addUser(self, username, password, active=False, roles=["user"]):
		if username in self._users.keys():
			raise UserAlreadyExists(username)

		self._users[username] = User(username, UserManager.createPasswordHash(password), active, roles)
		self._dirty = True
		self._save()

	def changeUserActivation(self, username, active):
		if not username in self._users.keys():
			raise UnknownUser(username)

		if self._users[username]._active != active:
			self._users[username]._active = active
			self._dirty = True
			self._save()

	def changeUserRoles(self, username, roles):
		if not username in self._users.keys():
			raise UnknownUser(username)

		user = self._users[username]

		removedRoles = set(user._roles) - set(roles)
		self.removeRolesFromUser(username, removedRoles)

		addedRoles = set(roles) - set(user._roles)
		self.addRolesToUser(username, addedRoles)

	def addRolesToUser(self, username, roles):
		if not username in self._users.keys():
			raise UnknownUser(username)

		user = self._users[username]
		for role in roles:
			if not role in user._roles:
				user._roles.append(role)
				self._dirty = True
		self._save()

	def removeRolesFromUser(self, username, roles):
		if not username in self._users.keys():
			raise UnknownUser(username)

		user = self._users[username]
		for role in roles:
			if role in user._roles:
				user._roles.remove(role)
				self._dirty = True
		self._save()

	def changeUserPassword(self, username, password):
		if not username in self._users.keys():
			raise UnknownUser(username)

		passwordHash = UserManager.createPasswordHash(password)
		user = self._users[username]
		if user._passwordHash != passwordHash:
			user._passwordHash = passwordHash
			self._dirty = True
			self._save()

	def removeUser(self, username):
		if not username in self._users.keys():
			raise UnknownUser(username)

		del self._users[username]
		self._dirty = True
		self._save()

	def findUser(self, username=None):
		if username is None:
			return None

		if username not in self._users.keys():
			return None

		return self._users[username]

	def getAllUsers(self):
		return map(lambda x: x.asDict(), self._users.values())

##~~ Exceptions

class UserAlreadyExists(Exception):
	def __init__(self, username):
		Exception.__init__(self, "User %s already exists" % username)

class UnknownUser(Exception):
	def __init__(self, username):
		Exception.__init__(self, "Unknown user: %s" % username)

class UnknownRole(Exception):
	def _init_(self, role):
		Exception.__init__(self, "Unknown role: %s" % role)

##~~ User object

class User(UserMixin):
	def __init__(self, username, passwordHash, active, roles):
		self._username = username
		self._passwordHash = passwordHash
		self._active = active
		self._roles = roles

	def asDict(self):
		return {
			"name": self._username,
			"active": self.is_active(),
			"admin": self.is_admin(),
			"user": self.is_user()
		}

	def check_password(self, passwordHash):
		return self._passwordHash == passwordHash

	def get_id(self):
		return self._username

	def get_name(self):
		return self._username

	def is_active(self):
		return self._active

	def is_user(self):
		return "user" in self._roles

	def is_admin(self):
		return "admin" in self._roles

##~~ DummyUser object to use when accessControl is disabled

class DummyUser(User):
	def __init__(self):
		User.__init__(self, "dummy", "", True, UserManager.valid_roles)

	def check_password(self, passwordHash):
		return True