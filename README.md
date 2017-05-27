# titlebot-ng

An open live-voting bot plugin for [Errbot](http://errbot.io/).

This Errbot plugin has been developed primarily to offer a live-voting for titles of the german photo podcast [Happy Shooting](http://www.happyshooting.de/podcast/) in its chatroom. 
The network used there is Slack.
titlebot-ng has not been tested with other errbot network backends but should work with them, too. (Unless you use the HSLive Slack streaming feature which extracts timestamps from the Slack backend).
The bot is able to run multiple votings in parallel (but limited to one voting per channel).

The bot itself does not join or part any channels on its own, errbot offers distinct facilities and modules (namely: ChatRoom) for this task.

titlebot-ng is the successor of the ZNC plugin [titlebot](https://github.com/markusj/znc-modules) which has been used previously in freenode/##happyshooting until the chatroom was migrated to Slack.
Since IRC does not enforce unique user identities (nicknames can change at any time), titlebot implemented some countermeasures against sybil attacks.
In contrast, the implementation of titlebot-ng is network backend agnoistic and does not try to identify malicous behavior.

## Usage ##

Errbot prints these usage hints if you type !help

For details, see !command -h

 * *!add* - usage: add [-h] [-c CHANNEL] option_text [option_text ...]
 * *!rm* - usage: rm [-h] [-c CHANNEL] option_id
 * *!vote* - usage: vote [-h] [-c CHANNEL] option_id
 * *!revoke* - usage: revoke [-h] [-c CHANNEL] [user]
 * *!enable* - usage: enable [-h] [-c CHANNEL]
 * *!disable* - usage: disable [-h] [-c CHANNEL]
 * *!countdown* - usage: countdown [-h] [--disable] [--list] [-c CHANNEL] [delay]
 * *!reset* - usage: reset [-h] [-c CHANNEL]
 * *!list* - usage: list [-h] [--public] [-c CHANNEL] [list_mode]
 * *!tb channel* - usage: tb_channel [-h] [-c CHANNEL] operation
 * *!tb admin* - usage: tb_admin [-h] [-c CHANNEL] operation admins [admins ...]
 * *!tb apikey* - usage: tb_apikey [-h] [-c CHANNEL] [key]
 * *!dump* - dumps all internal state (owner-only command)

titlebot-ng must be configured to monitor a channel, this is done by `!tb channel` (see help for details).
Administrators for the bot are configured on a per-channel basis using `!tb admin`.
The Errbot owner is always recognized as bot administrator.

Voting is controlled by bot administrators using `!enable`, `!disable` and `!reset`.
Regular users can `!add` own proposals, `!vote` for them or `!revoke` their vote.
They can also obtain a private `!list` of all options.

Administrators are additionally allowed to !revoke the vote of an other user.
They may `!rm` duplicated or inapprobiate options and use `!list --public` to print all options or results public within the channel.

The bot is also able to forward all non-bot-related conversations to a web-page. Since this feature is used for the Happy Shooting website, it is hardcoded at moment, but might be easily extended if required. Conversion of emojis to UTF relies on the [emoji](https://pypi.python.org/pypi/emoji) package to be installed (optional).
