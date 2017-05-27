from errbot import BotPlugin, botcmd, arg_botcmd, webhook
from errbot.backends.base import RoomDoesNotExistError, UserDoesNotExistError

import logging
import math
import time


log = logging.getLogger(__name__)



class VotingOption:
    # id            int
    # text          string
    # votes         int
    # deleted       boolean
    
    def __init__(self, id, text):
        self.id = id
        self.text = text
        self.votes = 0
        self.deleted = False



class UserVote:
    # user          Person
    # option        Index for ChanInfo.options
    
    def __init__(self, user, option):
        self.user = user
        self.option = option



class ChanConfig:
    # channel       string
    # admins        list of string

    def __init__(self, room, admins):
        self.channel = str(room)
        self.admins = admins[:]



class ChanInfo:
    # channel       Room
    # admins        list of string
    # options       list of VotingOption
    # userVotes     list of UserVote
    # enabled       boolean
    # countdownTS   float
    # countdownVal  integer

    def __init__(self, chan, adminList):
        self.channel = chan
        self.admins = adminList
        self.options = [ ]
        self.userVotes = [ ]
        self.reset()


    def reset(self):
        self.options.clear()
        self.userVotes.clear()
        self.enabled = False
        self.resetCountdown()


    def resetCountdown(self):
        self.countdownTS = -1
        self.countdownVal = -1;


    # user: Person
    def isAdmin(self, user):
        return str(user.person) in self.admins


    # user: Person
    def findVote(self, user):
        for vote in self.userVotes:
            if vote.user == user:
                return vote
        
        return None

    # user: Person, option: int -> int ( >= 0: ACK, -1: No such option, <-1: -oldVote - 2)
    def vote(self, user, option):
        if len(self.options) <= option or self.options[option].deleted:
            return -1
        
        oldVote = self.findVote(user)
        
        if oldVote is not None:
            return -oldVote.option - 2
        
        self.options[option].votes += 1
        self.userVotes.append(UserVote(user, option))
        
        return option


    # user: Person -> int
    def revoke(self, user):
        oldVote = self.findVote(user)
        
        if oldVote is None:
            return -1
        
        self.options[oldVote.option].votes -= 1
        self.userVotes[:] = [ vote for vote in self.userVotes if vote.user != user ]
        
        return oldVote.option
    
    
    # option: str -> int
    def addOption(self, option):
        result = len(self.options)
        newOption = VotingOption(result, option)
        
        self.options.append(newOption)
        
        return result
    
    
    # option: int -> list of Person
    def delOption(self, option):
        if option >= len(self.options) or self.options[option].deleted:
            return None
        
        voteOpt = self.options[option]
        result = [ ]
        
        for vote in self.userVotes:
            if option == vote.option:
                result.append(vote.user)
                voteOpt.votes -= 1
        
        self.userVotes[:] = [ vote for vote in self.userVotes if vote.option != option ]
        
        voteOpt.deleted = True
        
        return result
    
    
    # admin: string
    def addAdmin(self, admin):
        if admin not in self.admins:
            self.admins.append(admin)
        
        
    # admin: string
    def delAdmin(self, admin):
        self.admins[:] = [ name for name in self.admins if name != admin ]
    
    
    # -> ChanConfig
    def exportConfig(self):
        return ChanConfig(self.channel, self.admins)



class Titlebot(BotPlugin):
    """
    I help you to do open polls
    
    Hint: The argument <channel> in commands is only required if you send the command as query/direct message.
    """
    
    # chans         list of ChanInfo
    # cbChan        list of ChanInfo
    # polling       bool
    
    
    def __init__(self, bot, name):
        super().__init__(bot, name)
        
        self.resetState()
    
    
    def resetState(self):
        self.chans = [ ]
        self.cbChan = [ ]
        self.polling = False
    
    
    # msg: Message, errStr: String
    def badArgs(self, msg, errStr = ""):
        self.send(msg.frm, "error: bad or missing argument. " + errStr)
    
    
    # msg: Message, channel: string -> Room
    def lookupChannel(self, msg, channel):
        try:
            room = self.query_room(channel)
        except (RoomDoesNotExistError, ValueError) as e:
            self.badArgs(msg, "unknown or invalid channel name. details:\n" + str(e))
            
            return None
        
        if room.joined:
            return room        
        else:
            self.badArgs(msg, "i am not a member of this channel")
            
            return None
    
    
    # msg: Message, channel: Room -> ChanInfo
    def lookupChanInfo(self, msg, channel):
        candidate = [ chan for chan in self.chans if chan.channel == channel ]
        
        if len(candidate) > 0:
            return candidate[0]
        else:
            self.badArgs(msg, "i do not listen to commands for this channel")
            
            return None


    # msg: Message, channel: String -> bool
    def testChannel(self, msg, channel):
        if channel is None:
            if len(self.chans) != 1 and msg.is_direct:
                self.send(msg.frm, "Which channel did you mean? Please specify the channel using the argument \"--channel\" <channel_name>")
                
                return False
        else: # test if user occupies the requested channel
            for room in self.rooms():
                if channel == str(room) and len([ occupant for occupant in room.occupants if msg.frm == occupant ]) > 0:
                    return True
            
            self.badArgs(msg, "i do only accept commands from users in my channels")
            
            return False
            
        return True
    
    
    # msg: Message, channel: String -> Room
    def inferChannel(self, msg, channel):
        if channel is not None:
            return lookupChannel(msg, channel)
        elif not msg.is_direct:
            return msg.to
        else: # direct message and only one configured channel
            if len(self.chans) == 1:
                return self.chans[0].channel
            else:
                self.send(msg.frm, "error: could not infer the channel. this is a bug and not your fault. sorry!")
                
                return None


    # person: Person, chan: ChanInfo -> bool
    def testAdmin(self, person, chan):
        if not chan.isAdmin(person) and str(person.person) not in self.bot_config.BOT_ADMINS:
            self.send(person, "Access denied. Administrative privileges are required to run this command.")
            
            return False
        
        return True
    
    
    # msg: Message
    def testOwner(self, msg):
        if str(msg.frm.person) not in self.bot_config.BOT_ADMINS:
            self.send(msg.frm, "Access denied. Only bot owners are allowed to run this command.")
            
            return False
        
        return True


    # msg: Message, channel: String -> (room, ChanInfo)
    def parseParams(self, msg, channel):
        if not self.testChannel(msg, channel):
            raise ValueError()
        
        room = self.inferChannel(msg, channel)   
        if room is None:
            raise ValueError()
                 
        chan = self.lookupChanInfo(msg, room)
        if chan is None:
            raise ValueError()
        
        return (room, chan)


    @arg_botcmd('-c', '--channel', type=str, help='required if you send the command as query/direct message')
    @arg_botcmd('option', metavar='option_id', type=int, help='the option number you want to vote for')
    def vote(self, msg, channel, option):
        """vote for option <option_id>"""
        
        try:
            room, chan = self.parseParams(msg, channel)
        except ValueError as e:
            return
        
        if not chan.enabled:
            self.send(msg.frm, "Voting has been disabled")
            
            return
        
        result = chan.vote(msg.frm, option - 1)
        
        if result == option - 1:
            self.send(msg.frm, "Vote for option " + str(option) + " accepted")
        elif result == -1:
            self.send(msg.frm, "Failed: There is no such option. Maybe it has been deleted?")
        else:
            self.send(msg.frm, "Vote rejected, you have already voted for option " + str(-result - 1))


    @arg_botcmd('-c', '--channel', type=str, help='required if you send the command as query/direct message')
    @arg_botcmd('user', nargs='?', type=str, help='the user whose vote is to be revoked (admin-only)')
    def revoke(self, msg, channel, user):
        """revoke (your) vote"""
        
        try:
            room, chan = self.parseParams(msg, channel)
        except ValueError as e:
            return
        
        person = msg.frm
        isAdmin = False
        
        if user is not None and str(person.person) != user:
            isAdmin = self.testAdmin(person, chan)
            
            if isAdmin:
                try:
                    person = self.build_identifier(user)
                except (UserDoesNotExistError, ValueError) as e:
                    self.badArgs(msg, "unknown user or invalid syntax, can not revoke vote. details:\n" + str(e))
                    
                    return
            else:
                return
        
        msgTo = msg.frm if not isAdmin else room
        
        if not chan.enabled and not isAdmin:
            self.send(msg.frm, "Voting has been disabled")
            
            return
        
        result = chan.revoke(person)
        
        if result >= 0:
            self.send(msgTo, "----- Vote by user " + str(person.person) + " for option " + str(result + 1) + " has been revoked")
        else:
            self.send(msg.frm, "Failed: No vote to revoke for user " + str(person.person))


    @arg_botcmd('-c', '--channel', type=str, help='required if you send the command as query/direct message')
    @arg_botcmd('lText', metavar='option_text', nargs='+', type=str, help='the text of your proposed option')
    def add(self, msg, channel, lText):
        """add an option with text <option_text> to the vote"""
        
        try:
            room, chan = self.parseParams(msg, channel)
        except ValueError as e:
            return
        
        option = ' '.join(lText)
        
        if not chan.enabled:
            self.send(msg.frm, "Voting has been disabled")
            return
        
        result = chan.addOption(option)
        
        if result >= 0:
            self.send(room, "----- Option " + str(result + 1) + " added: " + option)
        else:
            self.send(msg.frm, "----- Failed to add option")
        
        
    @arg_botcmd('-c', '--channel', type=str, help='required if you send the command as query/direct message')
    @arg_botcmd('option', metavar='option_id', type=int, help='the option number you want to delete')
    def rm(self, msg, channel, option):
        """delete the voting option <option_id> (admin only command)"""
        
        try:
            room, chan = self.parseParams(msg, channel)
        except ValueError as e:
            return
        
        if not self.testAdmin(msg.frm, chan):
            return
        
        revoked = chan.delOption(option - 1)
        
        out = [ ]
        
        if revoked is not None:
            for user in revoked:
                out.append("----- Vote by user " + str(user.person) + " for option " + str(option) + " has been revoked -----")
                
            out.append("----- Option " + str(option) + " has been deleted by admin " + str(msg.frm.person) + " -----")
            
            self.send(room, '\n'.join(out))
        else:
            self.send(msg.frm, "Failed to delete option. Does it exist or has it already been deleted by someone else?")


    @arg_botcmd('-c', '--channel', type=str, help='required if you send the command as query/direct message')
    def enable(self, msg, channel):
        """enable/resume voting (admin only command)"""
        
        try:
            room, chan = self.parseParams(msg, channel)
        except ValueError as e:
            return
        
        if not self.testAdmin(msg.frm, chan):
            return
            
        if not chan.enabled:
            self.send(room, "----- Voting has been ENABLED! -----")
        else:
            self.send(msg.frm, "Voting was already " + "enabled" if chan.enabled else "disabled")
            
        chan.enabled = True


    @arg_botcmd('-c', '--channel', type=str, help='required if you send the command as query/direct message')
    def disable(self, msg, channel):
        """disable/pause voting. It might be continued later. Also resets the countdown timer, if running (admin only command)"""
        
        try:
            room, chan = self.parseParams(msg, channel)
        except ValueError as e:
            return
        
        if not self.testAdmin(msg.frm, chan):
            return
        
        if chan.enabled:
            self.send(room, "----- Voting has been DISABLED! -----")
            self.resetCountdown(chan)
        else:
            self.send(msg.frm, "Voting was already " + "enabled" if chan.enabled else "disabled")
            
        chan.enabled = False


    @arg_botcmd('-c', '--channel', type=str, help='required if you send the command as query/direct message')
    @arg_botcmd('--disable', '-d', action='store_true', help='disables a running countdown')
    @arg_botcmd('--list', '-l', dest='doList', action='store_true', help='lists all vote options before the countdown starts')
    @arg_botcmd('delay', nargs='?', type=int, default='60', help='countdown delay (in seconds). Negative values have the same effect as --disable. A value of zero ends the voting immediately. default=60sec')
    def countdown(self, msg, channel, disable, doList, delay):
        """start/stop a countdown to end the voting. Might be called again to change the counter value (admin only command)"""
        
        try:
            room, chan = self.parseParams(msg, channel)
        except ValueError as e:
            return
        
        if not self.testAdmin(msg.frm, chan):
            return
        
        if not chan.enabled:
            self.send(msg.frm, "Failed: Voting is disabled")
            return
        
        if disable or delay < 0:
            if self.resetCountdown(chan):
                self.send(room, "----- Countdown timer has been disabled")
            else:
                self.send(msg.frm, "Countdown timer was not running")
            return
        
        if delay == 0:
            self.setCountdown(chan, delay)
            return
        
        # regular case, delay > 0
        delayMins = math.floor(delay / 60)
        delaySecs = delay % 60
        delayStr = ""
        
        if delayMins > 0:
            delayStr = " " + str(delayMins) + "min"
        if delaySecs > 0:
            delayStr = delayStr + " " + str(delaySecs) + "sec"
        
        if doList:
            self.printOptions(room, chan)
        
        if self.setCountdown(chan, delay):
            self.send(room, "----- Countdown timer has been enabled. Voting will end in" + delayStr)
        else:
            self.send(room, "----- Countdown timer has been changed. Voting will end in" + delayStr)
    
    
    def startPoller(self):
        if not self.polling:
            self.start_poller(1, self.pollCallback)
        
        self.polling = True
    
    
    def stopPoller(self):
        if self.polling:
            self.stop_poller(self.pollCallback)
        
        self.polling = False
    
    
    # chan: ChanInfo, timeout: integer -> bool
    def setCountdown(self, chan, timeout):
        now = time.time()
        chan.countdownTS = now + timeout
        chan.countdownVal = timeout
        
        result = False
        
        if chan not in self.cbChan:
            self.cbChan.append(chan)
            
            result = True
            
        self.startPoller()
        
        return result
    
    
    # chan: ChanInfo -> bool
    def resetCountdown(self, chan):
        if chan not in self.cbChan:
            return False
        
        self.cbChan = [ c for c in self.cbChan if c != chan ]
        
        chan.resetCountdown()
        
        if len(self.cbChan) == 0:
            self.stopPoller()
        
        return True

    
    def pollCallback(self):
        now = time.time()
        
        for chan in self.cbChan:
            remaining = int(round(chan.countdownTS - now))
            # ensure no time step is skipped
            while chan.countdownVal > remaining:
                chan.countdownVal -= 1
                self.countdownProcessPoll(chan, chan.countdownVal)
        
        # cleanup ...
        # ...timed-out channels
        self.cbChan = [ c for c in self.cbChan if c.countdownTS >= 0 ]
        # ... and poller itself
        if len(self.cbChan) == 0:
            self.stopPoller()


    # chan: ChanInfo, remaining: integer
    def countdownProcessPoll(self, chan, remaining):
        if chan not in self.chans:
            return # got removed in between
    
        room = chan.channel
        
        if remaining <= 0:
            # time over
            chan.resetCountdown()
            chan.enabled = False
            
            self.send(room, "----- Countdown expired: Voting has been DISABLED")
            self.printResults(room, chan)
        elif remaining <= 5:
            self.send(room, "----- Countdown: " + str(remaining) + "sec remaining. Time is running out!")
        elif remaining <  3*10:
            # 10s steps
            if remaining % 10 == 0:
                self.send(room, "----- Countdown: " + str(remaining) + "sec remaining. Hurry up!")
        elif remaining <= 3*15:
            # 15s steps
            if remaining % 15 == 0:
                self.send(room, "----- Countdown: " + str(remaining) + "sec remaining. We are getting closer ...")
        elif remaining <= 3*30:
            # 30s steps
            if remaining % 30 == 0:
                self.send(room, "----- Countdown: " + str(remaining) + "sec remaining.")
        elif remaining <= 3*60:
            # 1m steps
            if remaining % 60 == 0:
                self.send(room, "----- Countdown: " + str(int(remaining / 60)) + "min remaining.")
        else:
            # 5m steps
            if remaining % (5*60) == 0:
                self.send(room, "----- Countdown: " + str(int(remaining / 60)) + "min remaining.")


    @arg_botcmd('-c', '--channel', type=str, help='required if you send the command as query/direct message')
    def reset(self, msg, channel):
        """resets (and disables) the voting, drops all options and votes (admin only command)"""
        
        try:
            room, chan = self.parseParams(msg, channel)
        except ValueError as e:
            return
        
        if not self.testAdmin(msg.frm, chan):
            return
        
        self.resetCountdown(chan)
        chan.reset()
        
        self.send(room, "----- All votes have been reset -----")


    @arg_botcmd('-c', '--channel', type=str, help='required if you send the command as query/direct message')
    @arg_botcmd('--public', '-p', action='store_true', help='send list public to channel (default: private as query/direct message)')
    @arg_botcmd('sListMode', metavar='list_mode', nargs='?', type=str, default='options', choices=['options', 'results', 'votes'], help='listing modes: options, results, votes')
    def list(self, msg, channel, public, sListMode):
        """lists vote options, voting results or individual votes optionally public in channel (otherwise as query/direct message). admin-only: individual votes and public listing"""
        
        try:
            room, chan = self.parseParams(msg, channel)
        except ValueError as e:
            return
        
        if (public or sListMode == "votes") and not self.testAdmin(msg.frm, chan):
            return
        
        msgTo = msg.frm if not public else room
        
        if sListMode == "options":
            self.printOptions(msgTo, chan)
        elif sListMode == "results":
            self.printResults(msgTo, chan)
        elif sListMode == "votes":
            self.printVotes(msgTo, chan)


    # msgTo: Identity, chanInfo: chanInfo
    def printOptions(self, msgTo, chanInfo):
        out = [ ]
        
        out.append("----- Vote options (first number: id) -----")
        
        for option in chanInfo.options:
            if not option.deleted:
                out.append("  " + str(option.id + 1) + ") " + option.text + " (" + str(option.votes) + " votes)")
        
        out.append("----- Vote options end -----")
        
        self.send(msgTo, '\n'.join(out))


    # msgTo: Identity, chanInfo: chanInfo
    def printResults(self, msgTo, chanInfo):
        out = [ ]
        
        options = chanInfo.options.copy()
        options.sort(key=lambda option :option.votes, reverse=True)
        
        out.append("----- Vote results (first number is the placement, NOT the id) -----")
        
        index = 1
        for option in options:
            if not option.deleted and option.votes > 0:
                out.append("  " + str(index) + ". " + option.text + " (Option " + str(option.id + 1) + " with " + str(option.votes) + " votes)")
                index += 1
        
        out.append("----- Vote results end -----")
        
        self.send(msgTo, '\n'.join(out))


    # msgTo: Identity, chanInfo: chanInfo
    def printVotes(self, msgTo, chanInfo):
        out = [ ]
        options = [ ]
        
        for i in range(len(chanInfo.options)):
            options.append([ ])
        
        for vote in chanInfo.userVotes:
            options[vote.option].append(vote)
        
        out.append("----- Vote list begin -----")
        
        for optionId, votes in enumerate(options):
            option = chanInfo.options[optionId]
            
            if option.votes > 0:
                out.append("  Option " + str(optionId + 1) + " (deleted=" + str(option.deleted) + "): " + option.text)
            
                for vote in votes:
                    out.append("    " + str(vote.user))
        
        out.append("----- Vote list end -----")
        
        self.send(msgTo, '\n'.join(out))
    
    
    @botcmd
    def dump(self, msg, args):
        """dumps all internal state (owner-only command)"""
        
        if not self.testOwner(msg):
            return
        
        out = [ ]
        
        out.append("----- chans -----")
        # chans             list of ChanInfo
        for info in self.chans:
            out.append("  name: " + str(info.channel))
            out.append("  ----- admins begin -----")
            # admins        list of string
            for admin in info.admins:
                out.append("    admin: " + admin)
            out.append("  ----- admins end -----")
            out.append("  ----- options begin -----")
            # options       list of VotingOption
            for option in info.options:
                out.append("    id: " + str(option.id))
                out.append("    text: " + option.text)
                out.append("    votes: " + str(option.votes))
                out.append("    deleted: " + str(option.deleted))
                out.append("    ----------")
            out.append("  ----- options end -----")
            out.append("  ----- userVotes begin -----")
            # userVotes     list of UserVote
            for userVote in info.userVotes:
                out.append("    " + str(userVote.user) + " -> " + str(userVote.option))
            out.append("  ----- userVotes end -----")
            out.append("  enabled: " + str(info.enabled))
            out.append("----------")
        
        out.append("----- callback polling chans -----")
        out.append("  polling: " + str(self.polling))
        for info in self.cbChan:
            out.append("  name: " + str(info.channel))
            out.append("----------")
        
        out.append("----- config -----")
        ccfg = self.tryLoadCfg()
        for cfg in ccfg:
            out.append("  name: " + cfg.channel)
            out.append("  ----- admins begin -----")
            # admins        list of string
            for admin in cfg.admins:
                out.append("    admin: " + admin)
            out.append("  ----- admins end -----")
        
        out.append("----- dump end -----")
        
        self.send(msg.frm, '\n'.join(out))
    
    
    # msg: Message, channel: String -> bool
    def testAdminChannel(self, msg, channel):
        if channel is None and len(self.rooms()) !=1 and msg.is_direct:
            self.send(msg.frm, "Which channel did you mean? Please specify the channel using the argument \"--channel\" <channel_name>")
            
            return False
        else:
            return True
    
    
    # msg: Message, channel: String -> Room
    def inferAdminChannel(self, msg, channel):
        if channel is not None:
            return self.lookupChannel(msg, channel)
        elif not msg.is_direct:
            return msg.to
        else: # direct message and only one configured channel
            if len(self.rooms()) == 1:
                return self.rooms()[0]
            else:
                self.send(msg.frm, "error: could not infer the channel. this is a bug and not your fault. sorry!")
                
                return None
    
    
    # -> list of ChanConfig
    def tryLoadCfg(self):
        try:
            return self['ccfg']
        except:
            return [ ]
    
    
    @arg_botcmd('-c', '--channel', type=str, help='required if you send the command as query/direct message')
    @arg_botcmd('-o', '--oldname', type=str, help='old channel name, required for operation "mv"')
    @arg_botcmd('op', metavar='operation', type=str, choices=['add', 'rm', 'mv'], help='operations: add, rm, mv')
    def tb_channel(self, msg, channel, oldname, op):
        """ Configures titlebot to offer/not offer its service in a channel. (owner-only command)"""
        #Note: errbot does not update Slack channel names until it is restarted
        #thus, "mv" to update the configuration of a renamed channel requires a restart
        
        if not self.testOwner(msg):
            return
        
        if not self.testAdminChannel(msg, channel):
            return
        
        if op == "add":
            self.doAddChannel(msg, channel)
        elif op == "rm":
            self.doRemoveChannel(msg, channel)
        elif op == "mv":
            self.doMoveChannel(msg, channel, oldname)
        else:
            self.send(msg.frm, "error: unknown operation. please refer to help for further advice.")
    
    
    # msg: Message, channel: String
    def doAddChannel(self, msg, channel):
        room = self.inferAdminChannel(msg, channel)
        
        if room is None:
            return
        
        for chan in self.chans:
            if chan.channel == room:
                self.send(msg.frm, "Channel is already configured")
                
                return
        
        ccfg = self.tryLoadCfg()
        
        for cfg in ccfg:
            if cfg.channel == channel:
                self.send(msg.frm, "Channel is already configured")
                
                return
        
        chan = ChanInfo(room, [])
        self.chans.append(chan)
        ccfg.append(chan.exportConfig())
        
        self['ccfg'] = ccfg
        
        self.send(room, "titlebot was configured to serve in this channel by " + str(msg.frm.person))
    
    
    # msg: Message, channel: String
    def doRemoveChannel(self, msg, channel):        
        ccfg = self.tryLoadCfg()
        ccfg[:] = [ cfg for cfg in ccfg if cfg.channel != channel ]
        self['ccfg'] = ccfg
        
        room = None
        
        for chan in self.chans:
            if channel == str(chan.channel):
                room = chan.channel
        self.chans[:] = [ chan for chan in self.chans if channel != str(chan.channel) ]
        
        if room is not None:
            self.send(room, "titlebot service is no longer available in this channel, all options and votes are lost.")
    
    
    # msg: Message, channel: String, oldname: String
    def doMoveChannel(self, msg, channel, oldname):
        room = self.inferAdminChannel(msg, channel)
        
        if room is None:
            return
        
        for chan in self.chans:
            if chan.channel == room:
                self.send(msg.frm, "Channel is already configured")
                
                return
        
        ccfg = self.tryLoadCfg()
        
        admins = [ cfg.admins for cfg in ccfg if cfg.channel == oldname ]
        ccfg[:] = [ cfg for cfg in ccfg if cfg.channel != oldname ]
        
        if len(admins) == 1:
            chan = ChanInfo(room, admins[0])
            self.chans.append(chan)
            ccfg.append(chan.exportConfig())
            
            self['ccfg'] = ccfg
            
            self.send(room, "titlebot was migrated from channel " + oldname + " to this channel by " + str(msg.frm.person))
        
            return
        
        self.send(msg.frm, "error: a channel named " + oldname + " has not been configured previously")
    
    
    @arg_botcmd('-c', '--channel', type=str, help='required if you send the command as query/direct message')
    @arg_botcmd('lAdmins', metavar='admins', nargs='+', type=str, help='a list of admins')
    @arg_botcmd('op', metavar='operation', type=str, choices=['add', 'rm'], help='operations: add, rm')
    def tb_admin(self, msg, channel, lAdmins, op):
        """ Adds/removes users from the bot administrator list (owner-only command)"""
        
        if not self.testOwner(msg):
            return
        
        if not self.testAdminChannel(msg, channel):
            return
            
        room = self.inferAdminChannel(msg, channel)
        
        if room is None:
            return
        
        chan = self.lookupChanInfo(msg, room)
        
        if chan is None:
            return        
        
        if op != "add" and op != "rm":
            self.send(msg.frm, "error: unknown operation. please refer to help for further advice.")
            
            return
        
        for admin in lAdmins:
            if op == "add":
                chan.addAdmin(admin)
            else:
                chan.delAdmin(admin)
        
        ccfg = self.tryLoadCfg()
        ccfg[:] = [ cfg for cfg in ccfg if cfg.channel != str(room) ]
        ccfg.append(chan.exportConfig())
        self['ccfg'] = ccfg
        
        self.send(msg.frm, "admins configured")
        
    
    # room: Room
    def tryAddRoom(self, room):
        if len( [ chan for chan in self.chans if chan.channel == room ] ) > 0:
            return
        
        ccfg = self.tryLoadCfg()
        candidate = [ cfg for cfg in ccfg if cfg.channel == str(room) ]
        
        if len(candidate) > 0:
            self.chans.append(ChanInfo(room, candidate[0].admins))
        else:
            self.log.info("ignored unconfigured room " + str(room))
        
        return
    
    
    def activate(self):
        """
        Triggers on plugin activation
        """
        super(Titlebot, self).activate()
        
        self.resetState()
        
        for room in self.rooms():
            self.tryAddRoom(room)


    def deactivate(self):
        """
        Triggers on plugin deactivation
        """
        
        self.stopPoller()
        
        super(Titlebot, self).deactivate()


    def callback_connect(self):
        """
        Triggers when bot is connected
        """
        
        for room in self.rooms():
            self.tryAddRoom(room)

    def callback_room_joined(self, room):
        """
            Triggered when the bot has joined a MUC.

            :param room:
                An instance of :class:`~errbot.backends.base.MUCRoom`
                representing the room that was joined.
        """
        
        self.tryAddRoom(room)
        
    def callback_room_left(self, room):
        """
            Triggered when the bot has left a MUC.

            :param room:
                An instance of :class:`~errbot.backends.base.MUCRoom`
                representing the room that was left.
        """
        
        self.chans[:] = [ chan for chan in self.chans if room != chan.channel ]
        self.log.info("left room " + str(room))

